//
// This file is a part of UERANSIM project.
// Copyright (c) 2023 ALİ GÜNGÖR.
//
// https://github.com/aligungr/UERANSIM/
// See README, LICENSE, and CONTRIBUTING files for licensing details.
//

#include "task.hpp"

#include <gnb/gtp/task.hpp>
#include <gnb/rrc/task.hpp>

#include <arpa/inet.h>
#include <cstring>
#include <fstream>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

#include <utils/common.hpp>
#include <utils/logger.hpp>

namespace nr::gnb
{

// Receive exactly n bytes.
static bool RecvAll(int fd, char *buf, size_t n)
{
    size_t got = 0;
    while (got < n)
    {
        ssize_t r = ::recv(fd, buf + got, n - got, 0);
        if (r <= 0)
            return false;
        got += static_cast<size_t>(r);
    }
    return true;
}

// Receive one length-prefixed JSON message.
static std::string RecvMsg(int fd)
{
    uint32_t nlen = 0;
    if (!RecvAll(fd, reinterpret_cast<char *>(&nlen), 4))
        return {};
    uint32_t len = ntohl(nlen);
    if (len == 0 || len > 65536)
        return {};
    std::string buf(len, '\0');
    if (!RecvAll(fd, buf.data(), len))
        return {};
    return buf;
}

// Send one length-prefixed JSON message.
static bool SendMsg(int fd, const std::string &msg)
{
    uint32_t nlen = htonl(static_cast<uint32_t>(msg.size()));
    if (::send(fd, &nlen, 4, MSG_NOSIGNAL) != 4)
        return false;
    if (::send(fd, msg.data(), msg.size(), MSG_NOSIGNAL) !=
        static_cast<ssize_t>(msg.size()))
        return false;
    return true;
}

// Open a TCP connection to gnb2 and send the XnHandoverRequest.
// Returns the connected socket fd, or -1 on error.
static int XnConnect(const std::string &host, uint16_t port, const std::string &request)
{
    int sock = ::socket(AF_INET, SOCK_STREAM, 0);
    if (sock < 0)
        return -1;

    // Long timeout: must cover gnb2's dispatcher round-trip + UE handoff
    struct timeval tv{30, 0};
    ::setsockopt(sock, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    ::setsockopt(sock, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port   = htons(port);
    if (::inet_pton(AF_INET, host.c_str(), &addr.sin_addr) <= 0 ||
        ::connect(sock, reinterpret_cast<sockaddr *>(&addr), sizeof(addr)) < 0)
    {
        ::close(sock);
        return -1;
    }

    if (!SendMsg(sock, request))
    {
        ::close(sock);
        return -1;
    }

    return sock;
}

void NgapTask::triggerXnHandover(int ueId, const std::string &targetGnbAddress,
                                  uint16_t targetGnbPort, int sliceSst)
{
    if (m_ueCtx.count(ueId) == 0)
    {
        m_logger->err("Xn handover: UE %d not found", ueId);
        return;
    }

    auto *ue        = m_ueCtx[ueId];
    int64_t amfUeNgapId = ue->amfUeNgapId;
    int64_t ranUeNgapId = ue->ranUeNgapId;

    uint64_t t1 = utils::CurrentTimeMillis();

    // ── Build sessions string for gnb2 PathSwitchRequest ────────────────────
    // Format: "psi,upTeid,upAddrHex,qfi1+qfi2|psi2,..."
    std::string sessionsStr;
    for (auto &[psi, xnInfo] : ue->xnSessionInfo)
    {
        if (!sessionsStr.empty()) sessionsStr += "|";

        char hexBuf[3];
        std::string addrHex;
        for (int i = 0; i < xnInfo.upAddr.length(); i++)
        {
            std::snprintf(hexBuf, sizeof(hexBuf), "%02x",
                          static_cast<unsigned>(xnInfo.upAddr.data()[i]));
            addrHex += hexBuf;
        }

        std::string qfisStr;
        for (size_t i = 0; i < xnInfo.qfis.size(); i++)
        {
            if (i) qfisStr += "+";
            qfisStr += std::to_string(xnInfo.qfis[i]);
        }
        if (qfisStr.empty()) qfisStr = "1";

        sessionsStr += std::to_string(psi) + "," +
                       std::to_string(xnInfo.upTeid) + "," +
                       addrHex + "," + qfisStr;
    }

    // ── Step 1: Xn Preparation ───────────────────────────────────────────────
    // Send UE context to target gNB; gnb2 contacts dispatcher (PSW) before Ack.
    std::string xnPayload =
        "{\"type\":\"XnHandoverRequest\""
        ",\"ueId\":"          + std::to_string(ueId) +
        ",\"amfUeNgapId\":"   + std::to_string(amfUeNgapId) +
        ",\"ranUeNgapId\":"   + std::to_string(ranUeNgapId) +
        ",\"sliceSst\":"      + std::to_string(sliceSst) +
        ",\"sourceGnb\":\""   + m_base->config->xnAddress + "\"" +
        ",\"sessions\":\""    + sessionsStr + "\""
        "}";

    // Open connection and send request; keep socket open for staged reads.
    int xnSock = XnConnect(targetGnbAddress, targetGnbPort, xnPayload);
    if (xnSock < 0)
    {
        m_logger->err("Xn handover: preparation failed — target gNB unreachable at %s:%d",
                      targetGnbAddress.c_str(), targetGnbPort);
        return;
    }

    // Block until gnb2 sends XnHandoverAck (after dispatcher selection).
    std::string xnAck = RecvMsg(xnSock);
    if (xnAck.empty())
    {
        m_logger->err("Xn handover: no XnHandoverAck received");
        ::close(xnSock);
        return;
    }

    // t2: Ack received = Xn prep + dispatcher chain selection complete.
    uint64_t t2 = utils::CurrentTimeMillis();
    m_logger->debug("Xn: HandoverAck received: %s", xnAck.c_str());

    // ── Step 2: RRC Reconfiguration → UE (simulated) ─────────────────────────
    m_logger->info("Xn: RRC Reconfiguration sent to UE[%d] — UE switching to target cell [simulated]",
                   ueId);

    // ── Step 3: Wait for UE Context Release from gnb2 ────────────────────────
    // gnb2 sends UeContextRelease only after PathSwitchRequestAcknowledge from AMF.
    // This blocking read correctly captures the UE-switch + AMF path-switch time.
    std::string ueCtxRelease = RecvMsg(xnSock);
    ::close(xnSock);
    if (ueCtxRelease.empty())
    {
        m_logger->err("Xn handover: no UeContextRelease received");
        return;
    }

    // t3: Release received = UE switched + AMF path switch confirmed.
    uint64_t t3 = utils::CurrentTimeMillis();
    m_logger->debug("Xn: UeContextRelease received from gnb2: %s", ueCtxRelease.c_str());
    m_logger->info("Xn: UeContextRelease received from gnb2 — releasing source UE context");

    // ── Step 4: Self-release source UE context ───────────────────────────────
    // Open5GS AMF moves the UE's N2 association to gnb2 immediately on
    // PathSwitchRequest (ran_ue_switch_to_gnb) and never sends UE Context
    // Release Command back to gnb1.  gnb1 therefore self-releases:
    //   • AN_RELEASE  → gnb1 RRC sends RRC Release to UE → UE goes idle
    //   • UE_CONTEXT_RELEASE → gnb1 GTP tears down data-plane sessions
    //   • deleteUeContext → gnb1 NGAP purges its local UE record
    // The UE then rediscovers gnb2 (already in gnbSearchList) and reconnects.
    {
        auto w1 = std::make_unique<NmGnbNgapToRrc>(NmGnbNgapToRrc::AN_RELEASE);
        w1->ueId = ueId;
        w1->xnHandover = true;
        m_base->rrcTask->push(std::move(w1));

        auto w2 = std::make_unique<NmGnbNgapToGtp>(NmGnbNgapToGtp::UE_CONTEXT_RELEASE);
        w2->ueId = ueId;
        m_base->gtpTask->push(std::move(w2));

        deleteUeContext(ueId);
    }
    m_logger->info("Xn: source UE[%d] released — RRC Release sent, GTP torn down, context deleted", ueId);

    uint64_t t4 = utils::CurrentTimeMillis();

    // ── Latency logging ──────────────────────────────────────────────────────
    // t2-t1: Xn prep + PSW (dispatcher selection)
    // t3-t2: UE handoff + gnb2→AMF path switch confirmation
    // t4-t3: Source context release
    // t4-t1: Total handover latency
    m_logger->info("Xn HO latency | ue=%d sst=%d | "
                   "prep+psw=%llums ue-switch=%llums release=%llums total=%llums",
                   ueId, sliceSst,
                   (unsigned long long)(t2 - t1),
                   (unsigned long long)(t3 - t2),
                   (unsigned long long)(t4 - t3),
                   (unsigned long long)(t4 - t1));

    // Append one row per handover: sst,prep_psw_ms,ue_switch_ms,release_ms,total_ms
    {
        std::ofstream csv("/home/amirndr/5g-lab/xn_ho_latency.csv", std::ios::app);
        if (csv.is_open())
            csv << sliceSst << ","
                << (t2 - t1) << ","
                << (t3 - t2) << ","
                << (t4 - t3) << ","
                << (t4 - t1) << "\n";
    }
}

} // namespace nr::gnb
