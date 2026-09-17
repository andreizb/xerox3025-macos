#!/usr/bin/env python3
"""Rebuild pinned native sources in this project only; never invokes sudo/brew install."""
import argparse, hashlib, json, os, pathlib, shutil, subprocess, tarfile, urllib.request
ROOT=pathlib.Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--offline',action='store_true',help='use supplied archives and pristine source exports; never fetch source')
args=parser.parse_args()
SRC=ROOT/'upstream'; BUILD=ROOT/'build'; PREFIX=ROOT/'prefix'; TOOLS=ROOT/'build-tools'
for p in (SRC,BUILD,PREFIX,TOOLS,ROOT/'downloads'): p.mkdir(exist_ok=True)
LOCK=ROOT/'sources.lock.json'
lock=json.loads(LOCK.read_text()) if LOCK.exists() else {}
env=os.environ.copy()
env.update(PATH=f'{TOOLS}/bin:/opt/homebrew/opt/libtool/libexec/gnubin:/opt/homebrew/opt/gettext/bin:'+env['PATH'], MACOSX_DEPLOYMENT_TARGET='14.0', CC='/usr/bin/clang', CXX='/usr/bin/clang++', CFLAGS='-O2 -arch arm64', CXXFLAGS='-O2 -arch arm64', LDFLAGS=f'-arch arm64 -L{PREFIX}/lib -Wl,-rpath,@executable_path/../lib', CPPFLAGS=f'-I{PREFIX}/include', PKG_CONFIG_LIBDIR=f'{PREFIX}/lib/pkgconfig:/usr/lib/pkgconfig', PKG_CONFIG_PATH=f'{PREFIX}/lib/pkgconfig', ACLOCAL_PATH=f'{TOOLS}/share/aclocal:/opt/homebrew/share/aclocal')
def run(args,cwd):
 print('+', ' '.join(map(str,args)),flush=True); subprocess.run(list(map(str,args)),cwd=cwd,env=env,check=True)
def archive(name,url,dirname):
 file=ROOT/'downloads'/url.rsplit('/',1)[1]
 if not file.exists():
  if args.offline:raise RuntimeError('Missing offline source archive: '+file.name)
  urllib.request.urlretrieve(url,file)
 digest=hashlib.sha256(file.read_bytes()).hexdigest()
 if name not in lock or lock[name]['sha256']!=digest: raise RuntimeError('Source checksum missing or mismatched: '+name)
 dest=SRC/dirname
 if not dest.exists():
  with tarfile.open(file) as t:t.extractall(SRC,filter='data')
 return dest

def checkout(name, patches):
 entry=lock[name]; dest=SRC/entry['directory']
 pristine=ROOT/'pristine'/entry['directory']
 origin=dest/'.xerox-source-origin.json'
 if not dest.exists():
  if pristine.is_dir():
   manifest=json.loads((ROOT/'pristine/manifest.json').read_text())[name]
   if manifest['commit']!=entry['commit']:raise RuntimeError('Unexpected exported source revision: '+name)
   actual={str(p.relative_to(pristine)):hashlib.sha256(p.read_bytes()).hexdigest()
           for p in sorted(pristine.rglob('*')) if p.is_file()}
   if actual!=manifest['sha256']:raise RuntimeError('Exported source checksum mismatch: '+name)
   shutil.copytree(pristine,dest,symlinks=True)
   # A local repository confines git apply to this component. It does not
   # impersonate the upstream commit: the export manifest records that origin.
   run(['git','init',dest],ROOT)
   origin.write_text(json.dumps({'commit':entry['commit'],'source':'verified pristine export'})+'\n')
  else:
   if args.offline:raise RuntimeError('Missing offline source export: '+name)
   run(['git','init',dest],ROOT)
   run(['git','remote','add','origin',entry['url']],dest)
   run(['git','fetch','--depth=1','origin',entry['commit']],dest)
   run(['git','checkout','--detach','FETCH_HEAD'],dest)
 head=(json.loads(origin.read_text())['commit'] if origin.exists() else
       subprocess.check_output(['git','rev-parse','HEAD'],cwd=dest,text=True).strip())
 if head!=entry['commit']:raise RuntimeError('Unexpected source revision: '+name)
 for patch in patches:
  path=ROOT/'patches'/patch
  check=subprocess.run(['git','apply','--reverse','--check',str(path)],cwd=dest,capture_output=True)
  if check.returncode:run(['git','apply',path],dest)
 return dest

def auto(name,source,prefix,extra=()):
 work=BUILD/name;work.mkdir(exist_ok=True)
 if not (work/'built.ok').exists():
  run([source/'configure','--prefix='+str(prefix),*extra],work)
  run(['make','-j6'],work);run(['make','install'],work);(work/'built.ok').write_text('ok\n')

def cmake(name,source,extra=()):
 work=BUILD/name
 if not (work/'built.ok').exists():
  run(['cmake','-S',source,'-B',work,'-DCMAKE_POLICY_VERSION_MINIMUM=3.5','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_OSX_ARCHITECTURES=arm64','-DCMAKE_OSX_DEPLOYMENT_TARGET=14.0','-DCMAKE_INSTALL_PREFIX='+str(PREFIX),*extra],ROOT)
  run(['cmake','--build',work,'-j6'],ROOT);run(['cmake','--install',work],ROOT);(work/'built.ok').write_text('ok\n')
if subprocess.check_output(['uname','-m'],text=True).strip()!='arm64':raise SystemExit('Native ARM64 build required')
auto('m4',archive('m4','https://ftp.gnu.org/gnu/m4/m4-1.4.20.tar.xz','m4-1.4.20'),TOOLS)
auto('autoconf',archive('autoconf','https://ftp.gnu.org/gnu/autoconf/autoconf-2.72.tar.xz','autoconf-2.72'),TOOLS)
auto('automake',archive('automake','https://ftp.gnu.org/gnu/automake/automake-1.18.1.tar.xz','automake-1.18.1'),TOOLS)
auto('autoconf-archive',archive('autoconf-archive','https://ftp.gnu.org/gnu/autoconf-archive/autoconf-archive-2024.10.16.tar.xz','autoconf-archive-2024.10.16'),TOOLS)
auto('libusb-1.0.30',archive('libusb','https://github.com/libusb/libusb/releases/download/v1.0.30/libusb-1.0.30.tar.bz2','libusb-1.0.30'),PREFIX,('--disable-static',))
cmake('jpeg-3.2.0',archive('libjpeg-turbo','https://github.com/libjpeg-turbo/libjpeg-turbo/releases/download/3.2.0/libjpeg-turbo-3.2.0.tar.gz','libjpeg-turbo-3.2.0'),('-DENABLE_STATIC=OFF','-DWITH_TURBOJPEG=OFF'))
cmake('png-1.6.58',archive('libpng','https://download.sourceforge.net/libpng/libpng-1.6.58.tar.xz','libpng-1.6.58'),('-DPNG_STATIC=OFF','-DPNG_TESTS=OFF','-DPNG_TOOLS=OFF','-DZLIB_INCLUDE_DIR='+subprocess.check_output(['xcrun','--show-sdk-path'],text=True).strip()+'/usr/include','-DZLIB_LIBRARY='+subprocess.check_output(['xcrun','--show-sdk-path'],text=True).strip()+'/usr/lib/libz.tbd'))
sane=checkout('sane-backends',['sane-tcp-framing-and-source.patch'])
shutil.copy2(ROOT/'src/xerox_tcp_io.h',sane/'backend/xerox_tcp_io.h')
def autoreconf(source):
 # A self-bootstrapped m4 is preferred, but m4 compiled against the macOS 26
 # SDK dies inside aclocal. Fall back to any other m4 that can finish the job
 # rather than leaving the tree without a configure script.
 try:
  run(['autoreconf','-fi'],source); return
 except subprocess.CalledProcessError:
  pass
 # Homebrew keeps m4 keg-only, so its opt path is checked before any
 # /usr/bin/m4, which is far too old for this autoconf.
 for candidate in ('/opt/homebrew/opt/m4/bin/m4','/usr/local/opt/m4/bin/m4',
                   '/opt/homebrew/bin/m4','/opt/homebrew/bin/gm4',
                   '/usr/local/bin/m4','/usr/local/bin/gm4','/usr/bin/gm4','/usr/bin/m4'):
  if not os.access(candidate,os.X_OK) or os.path.realpath(candidate)==os.path.realpath(TOOLS/'bin/m4'):continue
  fallback=dict(env,M4=candidate)
  print('! bootstrapped m4 failed under aclocal; retrying with',candidate,flush=True)
  if subprocess.run(['autoreconf','-fi'],cwd=source,env=fallback).returncode==0:return
 raise RuntimeError('No usable m4: the bootstrapped one and every system m4 failed to run aclocal. Install a recent one (brew install m4) and rerun.')

if not (sane/'configure').exists():
 (sane/'.tarball-version').write_text('1.4.0.923a04e\n')
 autoreconf(sane)
auto('sane',sane,PREFIX,('--disable-nls','--disable-static','--without-avahi','--without-snmp','--without-systemd','--without-libcurl','--without-poppler-glib','--without-usb-record-replay','--without-v4l','--without-usb','--without-libtiff','--disable-locking','--enable-pthread', 'BACKENDS=xerox_mfp','ac_cv_lib_tiff_TIFFOpen=no'))
# Always rebuild our small backend after patch/header changes, including a
# previous stock-backend comparison. Build stamps apply only to dependencies.
run(['make','-j6'],BUILD/'sane/backend')
run(['make','install'],BUILD/'sane/backend')
airsane=checkout('AirSane',['airsane-isolated-macos-build.patch','airsane-identity-localonly.patch'])
# The Autotools rpath in LDFLAGS is already handled by AirSane's CMake target.
# Importing it into CMake's linker flags makes install_name_tool add it twice.
run(['cmake','-S',airsane,'-B',BUILD/'airsane','-DISOLATED_PREFIX='+str(PREFIX),'-DCMAKE_INSTALL_PREFIX='+str(PREFIX),'-DCMAKE_OSX_ARCHITECTURES=arm64','-DCMAKE_OSX_DEPLOYMENT_TARGET=14.0','-DCMAKE_BUILD_TYPE=Release','-DCMAKE_EXE_LINKER_FLAGS='],ROOT)
run(['cmake','--build',BUILD/'airsane','-j6'],ROOT)
run(['cmake','--install',BUILD/'airsane'],ROOT)
run(['/usr/bin/clang','-O2','-arch','arm64','-mmacosx-version-min=14.0',ROOT/'src/discover.c','-o',BUILD/'discover'],ROOT)
run(['/usr/bin/clang','-O2','-Wall','-Wextra','-Werror','-arch','arm64','-mmacosx-version-min=14.0',ROOT/'packaging/service-lock.c','-o',BUILD/'service-lock'],ROOT)
print('Native backend built in',PREFIX)
