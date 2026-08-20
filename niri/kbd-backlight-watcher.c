#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <fcntl.h>
#include <poll.h>
#include <glob.h>
#include <sys/wait.h>
#include <time.h>
#include <stdint.h>

static uint64_t get_time_ms(void) {
    struct timespec ts;
    clock_gettime(CLOCK_MONOTONIC, &ts);
    return (uint64_t)ts.tv_sec * 1000 + (uint64_t)ts.tv_nsec / 1000000;
}

static void show_osd(int pct, const char *status_str) {
    pid_t pid = fork();
    if (pid == 0) {
        char pct_hint[32];
        snprintf(pct_hint, sizeof(pct_hint), "int:value:%d", pct);

        char *args[] = {
            "notify-send",
            "-h", "string:x-canonical-private-synchronous:osd",
            "-h", pct_hint,
            "-u", "low",
            "-t", "1200",
            "-a", "osd",
            "-i", "keyboard-brightness-symbolic",
            "Keyboard Backlight",
            (char *)status_str,
            NULL
        };

        int devnull = open("/dev/null", O_WRONLY);
        if (devnull >= 0) {
            dup2(devnull, STDOUT_FILENO);
            dup2(devnull, STDERR_FILENO);
            close(devnull);
        }

        execvp("notify-send", args);
        _exit(1);
    } else if (pid > 0) {
        waitpid(pid, NULL, WNOHANG);
    }
}

static int read_int_from_file(const char *path) {
    int fd = open(path, O_RDONLY);
    if (fd < 0) return -1;
    char buf[32];
    ssize_t n = read(fd, buf, sizeof(buf) - 1);
    close(fd);
    if (n <= 0) return -1;
    buf[n] = '\0';
    return atoi(buf);
}

int main(void) {
    glob_t globbuf;
    char bright_path[512] = {0};
    char max_path[512] = {0};
    char hw_changed_path[512] = {0};

    // Find keyboard backlight device
    if (glob("/sys/class/leds/*kbd*/brightness", 0, NULL, &globbuf) == 0 && globbuf.gl_pathc > 0) {
        strncpy(bright_path, globbuf.gl_pathv[0], sizeof(bright_path) - 1);
    }
    globfree(&globbuf);

    if (bright_path[0] == '\0') {
        fprintf(stderr, "No keyboard backlight device found in /sys/class/leds/\n");
        return 1;
    }

    char *slash = strrchr(bright_path, '/');
    if (slash) {
        size_t dir_len = (size_t)(slash - bright_path);
        snprintf(max_path, sizeof(max_path), "%.*s/max_brightness", (int)dir_len, bright_path);
        snprintf(hw_changed_path, sizeof(hw_changed_path), "%.*s/brightness_hw_changed", (int)dir_len, bright_path);
    }

    int max_val = read_int_from_file(max_path);
    if (max_val <= 0) max_val = 1;

    int last_val = read_int_from_file(bright_path);
    uint64_t last_event_time = 0;

    struct pollfd fds[2];
    int nfds = 0;

    int fd_bright = open(bright_path, O_RDONLY);
    if (fd_bright >= 0) {
        fds[nfds].fd = fd_bright;
        fds[nfds].events = POLLPRI | POLLERR;
        nfds++;
    }

    int fd_hw = open(hw_changed_path, O_RDONLY);
    if (fd_hw >= 0) {
        fds[nfds].fd = fd_hw;
        fds[nfds].events = POLLPRI | POLLERR;
        nfds++;
    }

    char drain_buf[64];

    while (1) {
        while (waitpid(-1, NULL, WNOHANG) > 0);

        poll(fds, nfds, 200);

        int hw_fired = 0;
        for (int i = 0; i < nfds; i++) {
            if (fds[i].revents & (POLLPRI | POLLIN | POLLERR)) {
                hw_fired = 1;
            }
            lseek(fds[i].fd, 0, SEEK_SET);
            (void)read(fds[i].fd, drain_buf, sizeof(drain_buf));
        }

        int curr_val = read_int_from_file(bright_path);
        uint64_t now = get_time_ms();

        if (curr_val >= 0 && (curr_val != last_val || (hw_fired && (now - last_event_time > 250)))) {
            if (now - last_event_time > 200) {
                last_event_time = now;
                last_val = curr_val;

                if (max_val == 1) {
                    if (curr_val == 0) {
                        show_osd(0, "Off");
                    } else {
                        show_osd(100, "On");
                    }
                } else {
                    int pct = (curr_val * 100) / max_val;
                    if (pct > 100) pct = 100;
                    if (pct < 0) pct = 0;
                    char status_str[32];
                    if (pct == 0) {
                        snprintf(status_str, sizeof(status_str), "Off");
                    } else {
                        snprintf(status_str, sizeof(status_str), "%d%%", pct);
                    }
                    show_osd(pct, status_str);
                }
            }
        }
    }

    for (int i = 0; i < nfds; i++) {
        close(fds[i].fd);
    }

    return 0;
}
