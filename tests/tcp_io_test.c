/* SPDX-License-Identifier: GPL-2.0-or-later WITH SANE-exception */
#include <assert.h>
#include <pthread.h>
#include <signal.h>
#include <stdio.h>
#include <string.h>
#include <unistd.h>
#include "../src/xerox_tcp_io.h"
struct peer {int fd;int mode;};
static void *peer(void *ctx){struct peer *p=ctx;unsigned char cmd[4];size_t n=0;assert(!xm_read_exact(p->fd,cmd,4,&n,xm_now_ms()+1000));assert(!memcmp(cmd,"\x1b\xa8\x12\x00",4));
 unsigned char reply[]={0xa8,0,5,0x10,1,2,3,4};
 if(p->mode==0){for(unsigned i=0;i<sizeof(reply);i++){assert(write(p->fd,reply+i,1)==1);usleep(1000);}}
 if(p->mode==1)assert(write(p->fd,reply,5)==5);
 if(p->mode==2){reply[2]=255;assert(write(p->fd,reply,3)==3);}
 if(p->mode==3){reply[0]=0;assert(write(p->fd,reply,3)==3);}
 if(p->mode==4)usleep(200000);
 if(p->mode==5){assert(write(p->fd,reply,8)==8);assert(write(p->fd,reply,8)==8);}
 close(p->fd);return NULL;
}
int main(void){signal(SIGPIPE,SIG_IGN);int passed=0;
 for(int mode=0;mode<=5;mode++){int s[2];assert(!socketpair(AF_UNIX,SOCK_STREAM,0,s));struct peer p={s[1],mode};pthread_t th;assert(!pthread_create(&th,NULL,peer,&p));unsigned char data[16];memset(data,0xcc,sizeof(data));size_t len=sizeof(data);int64_t start=xm_now_ms();int r=xm_request(s[0],(const unsigned char*)"\x1b\xa8\x12\x00",4,data,&len,100);
  if(mode==0||mode==5){assert(r==0&&len==8);assert(data[8]==0xcc);if(mode==5){len=8;assert(!xm_request(s[0],NULL,0,data,&len,100));assert(len==8);}}
  else assert(r==-1);
  if(mode==1)assert(len==5);
  if(mode==2||mode==3)assert(len==3);
  if(mode==4)assert(len==0&&xm_now_ms()-start>=90&&xm_now_ms()-start<500);
  close(s[0]);pthread_join(th,NULL);passed++;
 }
 int s[2];assert(!socketpair(AF_UNIX,SOCK_STREAM,0,s));unsigned char data[6]={1,2,3,4,5,6},reply[6];assert(write(s[1],data,6)==6);size_t size=6;assert(!xm_request(s[0],NULL,0,reply,&size,100));assert(size==6&&!memcmp(data,reply,6));close(s[0]);close(s[1]);passed++;
 assert(!socketpair(AF_UNIX,SOCK_STREAM,0,s));close(s[1]);size=6;assert(xm_request(s[0],data,6,reply,&size,100)==-1);close(s[0]);passed++;
 printf("PASS: %d TCP cases (fragmentation, truncation, overflow, header, deadline, consecutive frames, raw pixels, closed peer)\n",passed);
}
