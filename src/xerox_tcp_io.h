/* SPDX-License-Identifier: GPL-2.0-or-later WITH SANE-exception
 * Exact bounded framing for xerox_mfp TCP. Command replies contain a 3-byte
 * prefix whose third byte gives payload length; image reads have known size.
 */
#ifndef XEROX_TCP_IO_H
#define XEROX_TCP_IO_H
#include <errno.h>
#include <poll.h>
#include <stdint.h>
#include <sys/socket.h>
#include <time.h>
static int64_t xm_now_ms(void) {
 struct timespec t;
 if(clock_gettime(CLOCK_MONOTONIC,&t))return 0;
 return (int64_t)t.tv_sec*1000+t.tv_nsec/1000000;
}
static int xm_wait(int fd,short events,int64_t until) {
 struct pollfd p={fd,events,0};
 for(;;){int64_t left=until-xm_now_ms();if(left<=0){errno=ETIMEDOUT;return -1;}
  int n=poll(&p,1,left>1000?1000:(int)left);
  if(n>0){if(p.revents&(events|POLLHUP))return 0;errno=EIO;return -1;}
  if(n<0 && errno!=EINTR)return -1;
 }
}
static int xm_write_all(int fd,const unsigned char *data,size_t size,int64_t until) {
 size_t off=0;
 while(off<size){if(xm_wait(fd,POLLOUT,until))return -1;
  ssize_t n=send(fd,data+off,size-off,0);
  if(n>0)off+=(size_t)n;else if(n<0&&(errno==EINTR||errno==EAGAIN))continue;else return -1;
 }return 0;
}
static int xm_read_exact(int fd,unsigned char *data,size_t size,size_t *count,int64_t until){
 while(*count<size){if(xm_wait(fd,POLLIN,until))return -1;
  ssize_t n=recv(fd,data+*count,size-*count,0);
  if(n>0)*count+=(size_t)n;else if(n<0&&(errno==EINTR||errno==EAGAIN))continue;else{errno=EIO;return -1;}
 }return 0;
}
static int xm_request(int fd,const unsigned char *cmd,size_t cmdlen,unsigned char *reply,size_t *size,int timeout_ms){
 int64_t until=xm_now_ms()+timeout_ms;size_t count=0,capacity=size?*size:0;
 if(size)*size=0;
 if(cmd&&cmdlen&&xm_write_all(fd,cmd,cmdlen,until))return -1;
 if(!reply)return 0;
 if(!size||!capacity){errno=EINVAL;return -1;}
 size_t target=capacity;
 if(cmd&&cmdlen){
  if(capacity<3){errno=EINVAL;return -1;}
  if(xm_read_exact(fd,reply,3,&count,until)){*size=count;return -1;}
  target=(size_t)reply[2]+3;
  if(reply[0]!=0xa8 || target>capacity){*size=count;errno=EPROTO;return -1;}
 }
 int status=xm_read_exact(fd,reply,target,&count,until);*size=count;return status;
}
#endif
