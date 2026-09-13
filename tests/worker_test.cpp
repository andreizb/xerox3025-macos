// SPDX-License-Identifier: MIT
#include "basic/workerthread.h"
#include <atomic>
#include <cassert>
#include <thread>
#include <vector>
#include <chrono>
int main() {
  WorkerThread worker;
  std::atomic<int> active{0}, completed{0};
  struct Call : WorkerThread::Callable {
    std::atomic<int>& active; std::atomic<int>& completed;
    Call(std::atomic<int>& a, std::atomic<int>& c):active(a),completed(c){}
    void onCall() override {
      assert(active.fetch_add(1)==0);
      std::this_thread::sleep_for(std::chrono::microseconds(200));
      active--; completed++;
    }
  };
  std::vector<std::thread> clients;
  for(int i=0;i<8;i++) clients.emplace_back([&](){
    for(int j=0;j<20;j++){Call call(active,completed);worker.executeSynchronously(call);}
  });
  for(auto& client:clients)client.join();
  assert(completed==160);
}
