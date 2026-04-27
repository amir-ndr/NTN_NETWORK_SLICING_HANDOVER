//
// This file is a part of UERANSIM project.
// Copyright (c) 2023 ALİ GÜNGÖR.
//
// https://github.com/aligungr/UERANSIM/
// See README, LICENSE, and CONTRIBUTING files for licensing details.
//

#pragma once

#include <atomic>
#include <thread>

namespace nr::gnb
{

struct TaskBase;

// TCP server that accepts incoming Xn handover requests from other gNBs.
// Runs as a background thread when xnAddress is configured.
// For each XnHandoverRequest, contacts the dispatcher (PathSwitchRequest)
// then replies with XnHandoverAck.
class XnTask
{
  public:
    explicit XnTask(TaskBase *base);
    ~XnTask();

    void start();
    void stop();

  private:
    void listenerLoop();
    void handleConnection(int connFd);

    TaskBase *m_base;
    std::thread m_thread;
    std::atomic<bool> m_running{false};
    int m_serverFd{-1};
};

} // namespace nr::gnb
