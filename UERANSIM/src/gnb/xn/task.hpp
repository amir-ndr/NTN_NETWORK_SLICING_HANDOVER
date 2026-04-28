//
// This file is a part of UERANSIM project.
// Copyright (c) 2023 ALİ GÜNGÖR.
//
// https://github.com/aligungr/UERANSIM/
// See README, LICENSE, and CONTRIBUTING files for licensing details.
//

#pragma once

#include <atomic>
#include <condition_variable>
#include <mutex>
#include <thread>

namespace nr::gnb
{

struct TaskBase;

class XnTask
{
  public:
    explicit XnTask(TaskBase *base);
    ~XnTask();

    void start();
    void stop();

    // Called by NgapTask when PathSwitchRequestAcknowledge arrives.
    void notifyPathSwitchComplete();

  private:
    void listenerLoop();
    void handleConnection(int connFd);

    TaskBase *m_base;
    std::thread m_thread;
    std::atomic<bool> m_running{false};
    int m_serverFd{-1};

    std::mutex m_pswMu;
    std::condition_variable m_pswCv;
    bool m_pswDone{false};
};

} // namespace nr::gnb
