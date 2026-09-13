/* SPDX-License-Identifier: MIT
 * Bounded native Bonjour discovery by IPP UUID. No cached IP addresses.
 */
#include <dns_sd.h>
#include <arpa/inet.h>
#include <errno.h>
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <sys/select.h>
#include <time.h>
#include <unistd.h>
#include <ctype.h>
#define MAX_SERVICES 64
struct candidate { DNSServiceRef ref; char name[256]; uint32_t interface; };
struct result { char uuid[128],host[1024],name[256]; uint16_t port; uint32_t interface; int found; };
static struct candidate candidates[MAX_SERVICES];
static int count;
static struct result result;
static void resolve_cb(DNSServiceRef ref, DNSServiceFlags flags,uint32_t interface,DNSServiceErrorType error,const char *full,const char *host,uint16_t port,uint16_t txtlen,const unsigned char *txt,void *ctx) {
 (void)ref;(void)flags;(void)full;
 if(error)return;
 uint8_t len=0; const char *uuid=TXTRecordGetValuePtr(txtlen,txt,"UUID",&len);
 if(!uuid || len!=strlen(result.uuid) || strncasecmp(uuid,result.uuid,len))return;
 if(strlen(host)>=sizeof(result.host))return;
 /* SANE's configuration syntax cannot quote whitespace in DNS host labels. */
 for(const char *p=host;*p;p++) if(!((*p>='a'&&*p<='z')||(*p>='A'&&*p<='Z')||(*p>='0'&&*p<='9')||*p=='.'||*p=='-'))return;
 strcpy(result.host,host);snprintf(result.name,sizeof(result.name),"%s",((struct candidate*)ctx)->name);
 result.port=ntohs(port);result.interface=interface;result.found=1;
}
static void browse_cb(DNSServiceRef ref,DNSServiceFlags flags,uint32_t interface,DNSServiceErrorType error,const char *name,const char *type,const char *domain,void *ctx) {
 (void)ref;(void)ctx;
 if(error || !(flags&kDNSServiceFlagsAdd) || count>=MAX_SERVICES)return;
 struct candidate *c=&candidates[count++];snprintf(c->name,sizeof(c->name),"%s",name);c->interface=interface;
 if(DNSServiceResolve(&c->ref,0,interface,name,type,domain,resolve_cb,c))c->ref=NULL;
}
static void json(const char *s){putchar('"');for(;*s;s++){unsigned char c=*s;if(c=='"'||c=='\\')putchar('\\');if(c<32)printf("\\u%04x",c);else putchar(c);}putchar('"');}
int main(int argc,char **argv) {
 if(argc<2 || argc>3 || strlen(argv[1])!=36 || (argc==3 && strcmp(argv[2],"--sane"))){fprintf(stderr,"usage: discover PRINTER-UUID [--sane]\n");return 64;}
 for(int i=0;i<36;i++)if((i==8||i==13||i==18||i==23)?argv[1][i]!='-':!isxdigit((unsigned char)argv[1][i]))return 64;
 strcpy(result.uuid,argv[1]);DNSServiceRef browser=NULL;
 DNSServiceErrorType err=DNSServiceBrowse(&browser,0,0,"_ipp._tcp","local.",browse_cb,NULL);
 if(err){fprintf(stderr,"Bonjour browse failed (%d)\n",err);return 69;}
 struct timespec start,now;clock_gettime(CLOCK_MONOTONIC,&start);
 while(!result.found){
  clock_gettime(CLOCK_MONOTONIC,&now);if(now.tv_sec-start.tv_sec>=10)break;
  fd_set fds;FD_ZERO(&fds);int maxfd=DNSServiceRefSockFD(browser);if(maxfd<0||maxfd>=FD_SETSIZE)break;FD_SET(maxfd,&fds);
  int ready_count=count;
  for(int i=0;i<ready_count;i++)if(candidates[i].ref){int fd=DNSServiceRefSockFD(candidates[i].ref);if(fd<0||fd>=FD_SETSIZE)continue;FD_SET(fd,&fds);if(fd>maxfd)maxfd=fd;}
  struct timeval wait={0,250000};int n=select(maxfd+1,&fds,NULL,NULL,&wait);if(n<0){if(errno==EINTR)continue;break;}
  if(n>0){if(FD_ISSET(DNSServiceRefSockFD(browser),&fds))DNSServiceProcessResult(browser);
   for(int i=0;i<ready_count;i++)if(candidates[i].ref){int fd=DNSServiceRefSockFD(candidates[i].ref);if(fd>=0&&fd<FD_SETSIZE&&FD_ISSET(fd,&fds))DNSServiceProcessResult(candidates[i].ref);}
  }
 }
 DNSServiceRefDeallocate(browser);for(int i=0;i<count;i++)if(candidates[i].ref)DNSServiceRefDeallocate(candidates[i].ref);
 if(!result.found){fprintf(stderr,"The configured printer UUID was not found within 10 seconds.\n");return 69;}
 if(argc==3 && !strcmp(argv[2],"--sane"))printf("tcp %s 9400\n",result.host);
 else {printf("{\"uuid\":");json(result.uuid);printf(",\"hostname\":");json(result.host);printf(",\"service_name\":");json(result.name);printf(",\"ipp_port\":%u,\"interface_index\":%u}\n",result.port,result.interface);}
 return 0;
}
