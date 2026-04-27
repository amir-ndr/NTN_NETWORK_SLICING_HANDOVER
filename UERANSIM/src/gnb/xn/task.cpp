//
// This file is a part of UERANSIM project.
// Copyright (c) 2023 ALİ GÜNGÖR.
//
// https://github.com/aligungr/UERANSIM/
// See README, LICENSE, and CONTRIBUTING files for licensing details.
//

#include "task.hpp"

#include <gnb/ngap/task.hpp>
#include <gnb/nts.hpp>
#include <gnb/types.hpp>
#include <utils/logger.hpp>

#include <chrono>
#include <arpa/inet.h>
#include <cerrno>
#include <cstdio>
#include <cstring>
#include <netinet/in.h>
#include <sys/socket.h>
#include <unistd.h>

namespace nr::gnb
{

// ── Wire helpers ──────────────────────────────────────────────────────────────

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

static std::string RecvMsg(int fd)
{
    uint32_t nlen = 0;
    if (!RecvAll(fd, reinterpret_cast<char *>(&nlen), 4))
        return {};
    uint32_t len = ntohl(nlen);
    if (len == 0 || len > 1024 * 1024)
        return {};
    std::string buf(len, '\0');
    if (!RecvAll(fd, buf.data(), len))
        return {};
    return buf;
}

static bool SendMsg(int fd, const std::string &msg)
{
    uint32_t nlen = htonl(static_cast<uint32_t>(msg.size()));
    if (::send(fd, &nlen, 4, MSG_NOSIGNAL) != 4)
        return false;
    if (::send(fd, msg.data(), msg.size(), MSG_NOSIGNAL) != static_cast<ssize_t>(msg.size()))
        return false;
    return true;
}

// ── Minimal JSON field extractor ──────────────────────────────────────────────

static std::string JsonGetString(const std::string &json, const std::string &key)
{
    std::string search = "\"" + key + "\"";
    size_t pos = json.find(search);
    if (pos == std::string::npos)
        return {};
    pos = json.find(':', pos + search.size());
    if (pos == std::string::npos)
        return {};
    pos = json.find_first_not_of(" \t\r\n", pos + 1);
    if (pos == std::string::npos)
        return {};
    if (json[pos] == '"')
    {
        size_t end = json.find('"', pos + 1);
        if (end == std::string::npos)
            return {};
        return json.substr(pos + 1, end - pos - 1);
    }
    size_t end = json.find_first_of(",}", pos);
    return json.substr(pos, end != std::string::npos ? end - pos : std::string::npos);
}

// ── Dispatcher contact ────────────────────────────────────────────────────────

static std::string ContactDispatcher(const std::string &host, uint16_t port,
                                      const std::string &payload)
{
    int s = ::socket(AF_INET, SOCK_STREAM, 0);
    if (s < 0)
        return {};

    struct timeval tv{5, 0};
    ::setsockopt(s, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    ::setsockopt(s, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(port);
    if (::inet_pton(AF_INET, host.c_str(), &addr.sin_addr) <= 0 ||
        ::connect(s, reinterpret_cast<sockaddr *>(&addr), sizeof(addr)) < 0)
    {
        ::close(s);
        return {};
    }

    SendMsg(s, payload);
    std::string resp = RecvMsg(s);
    ::close(s);
    return resp;
}

// ── XnTask ────────────────────────────────────────────────────────────────────

XnTask::XnTask(TaskBase *base) : m_base(base)
{
}

XnTask::~XnTask()
{
    stop();
}

void XnTask::start()
{
    if (m_base->config->xnAddress.empty())
        return;

    m_running = true;
    m_thread = std::thread(&XnTask::listenerLoop, this);
}

void XnTask::stop()
{
    m_running = false;
    if (m_serverFd >= 0)
    {
        ::shutdown(m_serverFd, SHUT_RDWR);
        ::close(m_serverFd);
        m_serverFd = -1;
    }
    if (m_thread.joinable())
        m_thread.join();
}

void XnTask::listenerLoop()
{
    auto *logger = m_base->logBase->makeLogger("xn");

    m_serverFd = ::socket(AF_INET, SOCK_STREAM, 0);
    if (m_serverFd < 0)
    {
        logger->err("Xn server: socket() failed: %s", std::strerror(errno));
        return;
    }

    int opt = 1;
    ::setsockopt(m_serverFd, SOL_SOCKET, SO_REUSEADDR, &opt, sizeof(opt));

    sockaddr_in addr{};
    addr.sin_family = AF_INET;
    addr.sin_port = htons(m_base->config->xnPort);
    if (::inet_pton(AF_INET, m_base->config->xnAddress.c_str(), &addr.sin_addr) <= 0)
    {
        logger->err("Xn server: invalid xnAddress: %s", m_base->config->xnAddress.c_str());
        return;
    }

    if (::bind(m_serverFd, reinterpret_cast<sockaddr *>(&addr), sizeof(addr)) < 0)
    {
        logger->err("Xn server: bind() failed on %s:%d — %s",
                    m_base->config->xnAddress.c_str(), m_base->config->xnPort, std::strerror(errno));
        return;
    }

    ::listen(m_serverFd, 10);
    logger->info("Xn server listening on %s:%d",
                 m_base->config->xnAddress.c_str(), m_base->config->xnPort);

    while (m_running)
    {
        int connFd = ::accept(m_serverFd, nullptr, nullptr);
        if (connFd < 0)
            break;
        std::thread([this, connFd]() { handleConnection(connFd); }).detach();
    }
}

void XnTask::handleConnection(int connFd)
{
    auto *logger = m_base->logBase->makeLogger("xn");

    struct timeval tv{5, 0};
    ::setsockopt(connFd, SOL_SOCKET, SO_RCVTIMEO, &tv, sizeof(tv));
    ::setsockopt(connFd, SOL_SOCKET, SO_SNDTIMEO, &tv, sizeof(tv));

    std::string msg = RecvMsg(connFd);
    if (msg.empty())
    {
        ::close(connFd);
        return;
    }

    logger->debug("Xn: received: %s", msg.c_str());

    std::string ueIdStr  = JsonGetString(msg, "ueId");
    std::string amfUeStr = JsonGetString(msg, "amfUeNgapId");
    std::string ranUeStr = JsonGetString(msg, "ranUeNgapId");
    std::string sstStr   = JsonGetString(msg, "sliceSst");
    std::string srcGnb   = JsonGetString(msg, "sourceGnb");

    int ueId = ueIdStr.empty() ? -1 : std::stoi(ueIdStr);
    int sst  = sstStr.empty()  ? 1  : std::stoi(sstStr);

    // ── PathSwitchRequest to dispatcher ──────────────────────────────────────
    double pswMs = 0.0;
    std::string selectedAmf = "127.0.0.5";

    if (!m_base->config->dispatcherAddress.empty())
    {
        std::string pswPayload =
            "{\"type\":\"PathSwitchRequest\""
            ",\"ueId\":" + ueIdStr +
            ",\"amfUeNgapId\":" + amfUeStr +
            ",\"ranUeNgapId\":" + ranUeStr +
            ",\"sliceSst\":" + sstStr +
            ",\"targetGnb\":\"" + m_base->config->xnAddress + "\""
            ",\"sourceGnb\":\"" + srcGnb + "\""
            "}";

        auto t0 = std::chrono::steady_clock::now();
        std::string pswResp = ContactDispatcher(m_base->config->dispatcherAddress,
                                                 m_base->config->dispatcherPort, pswPayload);
        pswMs = std::chrono::duration<double, std::milli>(
                    std::chrono::steady_clock::now() - t0).count();

        if (pswResp.empty())
            logger->err("Xn: dispatcher unreachable at %s:%d",
                        m_base->config->dispatcherAddress.c_str(), m_base->config->dispatcherPort);
        else
        {
            logger->debug("Xn: dispatcher reply (%.1fms): %s", pswMs, pswResp.c_str());
            std::string amf = JsonGetString(pswResp, "selectedAmf");
            if (!amf.empty())
                selectedAmf = amf;
        }
    }
    else
    {
        logger->debug("Xn: no dispatcher configured — skipping PathSwitchRequest");
    }

    // ── XnHandoverAck ─────────────────────────────────────────────────────────
    char pswBuf[32];
    std::snprintf(pswBuf, sizeof(pswBuf), "%.1f", pswMs);

    std::string ack =
        "{\"type\":\"XnHandoverAck\""
        ",\"ueId\":" + ueIdStr +
        ",\"sliceSst\":" + sstStr +
        ",\"status\":\"OK\""
        ",\"targetCell\":\"" + m_base->config->name + "\""
        ",\"selectedAmf\":\"" + selectedAmf + "\""
        ",\"pswLatencyMs\":" + pswBuf +
        "}";

    SendMsg(connFd, ack);
    logger->info("Xn: HandoverAck | ue=%d sst=%d psw=%.1fms selectedAmf=%s",
                 ueId, sst, pswMs, selectedAmf.c_str());

    // ── UeContextRelease (make-before-break) ──────────────────────────────────
    // In 3GPP: sent after UE camps on gnb2 and gnb2→AMF PathSwitch completes.
    // Here the PathSwitch (dispatcher) already completed above, so we send
    // the release immediately — gnb1 is blocked waiting for this message.
    std::string ctxRelease =
        "{\"type\":\"UeContextRelease\""
        ",\"ueId\":"    + ueIdStr +
        ",\"cause\":\"successful_handover\""
        "}";

    SendMsg(connFd, ctxRelease);
    logger->info("Xn: UeContextRelease sent to source gNB | ue=%d", ueId);
    ::close(connFd);

    // ── Trigger NGAP PathSwitchRequest to AMF ────────────────────────────────
    // Parse sessions from XnHandoverRequest: "psi,upTeid,upAddrHex,qfi1+qfi2|..."
    std::string sessStr   = JsonGetString(msg, "sessions");
    std::string amfUeStr2 = JsonGetString(msg, "amfUeNgapId");

    if (!sessStr.empty() && !amfUeStr2.empty())
    {
        auto nm = std::make_unique<NmGnbXnToNgap>(NmGnbXnToNgap::TRIGGER_PATH_SWITCH);
        nm->amfUeNgapId = std::stoll(amfUeStr2);

        std::string remaining = sessStr;
        while (!remaining.empty())
        {
            std::string entry;
            auto bar = remaining.find('|');
            if (bar != std::string::npos)
            {
                entry     = remaining.substr(0, bar);
                remaining = remaining.substr(bar + 1);
            }
            else
            {
                entry = remaining;
                remaining.clear();
            }

            // Split: psi , upTeid , upAddrHex , qfisStr
            size_t p0 = 0, p1 = entry.find(',', p0);
            if (p1 == std::string::npos) continue;
            NmGnbXnToNgap::SessionInfo si;
            si.psi = std::stoi(entry.substr(p0, p1 - p0));

            p0 = p1 + 1; p1 = entry.find(',', p0);
            if (p1 == std::string::npos) continue;
            si.upTeid = static_cast<uint32_t>(std::stoul(entry.substr(p0, p1 - p0)));

            p0 = p1 + 1; p1 = entry.find(',', p0);
            if (p1 == std::string::npos) continue;
            std::string addrHex = entry.substr(p0, p1 - p0);

            std::vector<uint8_t> addrBytes;
            for (size_t i = 0; i + 1 < addrHex.size(); i += 2)
                addrBytes.push_back(
                    static_cast<uint8_t>(std::stoul(addrHex.substr(i, 2), nullptr, 16)));
            si.upAddr = OctetString(std::move(addrBytes));

            p0 = p1 + 1;
            std::string qfisStr = entry.substr(p0);
            size_t q0 = 0;
            while (q0 <= qfisStr.size())
            {
                auto q1 = qfisStr.find('+', q0);
                std::string tok = (q1 != std::string::npos)
                                      ? qfisStr.substr(q0, q1 - q0)
                                      : qfisStr.substr(q0);
                if (!tok.empty())
                    si.qfis.push_back(std::stol(tok));
                if (q1 == std::string::npos) break;
                q0 = q1 + 1;
            }

            nm->sessions.push_back(std::move(si));
        }

        if (!nm->sessions.empty())
        {
            m_base->ngapTask->push(std::move(nm));
            logger->info("Xn: NGAP PathSwitchRequest triggered for amfUeId=%s", amfUeStr2.c_str());
        }
    }
}

} // namespace nr::gnb
