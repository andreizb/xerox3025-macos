/* SPDX-License-Identifier: MIT
 * Keep one service per installation, including direct diagnostic launches.
 * The descriptor deliberately survives exec so the kernel releases the lock
 * only after the service and its inherited children have stopped.
 */
#include <sys/file.h>
#include <sys/stat.h>
#include <fcntl.h>
#include <stdio.h>
#include <unistd.h>

int main(int argc, char **argv)
{
    if (argc < 3) {
        fputs("usage: service-lock LOCKFILE COMMAND [ARG ...]\n", stderr);
        return 64;
    }
    int fd = open(argv[1], O_RDWR | O_CREAT | O_NOFOLLOW, 0600);
    struct stat info;
    if (fd < 0 || fstat(fd, &info) || !S_ISREG(info.st_mode) || info.st_uid != getuid()) {
        fputs("Cannot open the private service lock.\n", stderr);
        return 73;
    }
    if (flock(fd, LOCK_EX | LOCK_NB)) {
        fputs("The bridge is already running for this installation.\n", stderr);
        close(fd);
        return 75;
    }
    execvp(argv[2], argv + 2);
    perror("Cannot start the bridge");
    close(fd);
    return 71;
}
