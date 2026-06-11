/*
 * SSH client example for ZX Spectrum + Spectranext.
 *
 * Prompts for a server hostname (user@host supported), opens a TCP socket on
 * port 22, and runs an interactive loop using poll_fd() to read from the socket
 * while also reading keyboard input.
 *
 * Spectranext handles SSH on port 22 transparently. During authentication the
 * co-processor may send control prompts (TRUST?, USER?, PASSWORD?) over the
 * socket; once the session is ready you will see CONNECTED and shell output.
 */

#include <stdio.h>
#include <string.h>
#include <input.h>
#include <sys/socket.h>
#include <netdb.h>
#include <sockpoll.h>
#include <spectranet.h>

#define SSH_PORT          22
#define HOST_MAX          64
#define RXBUF_SIZE        768
#define LINE_MAX          128
#define CURSOR_STEP_MS    25u
#define CURSOR_BLINK_TICKS 20u
#define SSH_BACKSPACE     127
#define KEY_WAIT_NONE     0
#define KEY_WAIT_ALL      1

static int ssh_ready;
static int key_armed = 1;
static int key_wait_mode;
static uint x_key_scancode;
static char rxbuf[RXBUF_SIZE];
static char ctrl_buf[RXBUF_SIZE];
static int ctrl_len;

static int cursor_active;
static int cursor_visible;
static int cursor_gap;
static unsigned cursor_blink_tick;

static int is_delete_key(int key)
{
    /* Rubout / backspace only; '0' is always a normal character. */
    return key == 8 || key == 12 || key == SSH_BACKSPACE;
}

static int is_text_key(int key)
{
    return (key >= 32 && key < 127) || key == 13 || key == 10;
}

static int poll_key(void)
{
    char key;

    if (!key_armed)
    {
        if (key_wait_mode == KEY_WAIT_ALL)
            in_WaitForNoKey();

        key_wait_mode = KEY_WAIT_NONE;
        key_armed = 1;
        return 0;
    }

    key = (char)in_Inkey();
    if (!key)
        return 0;

    key_armed = 0;

    if (is_delete_key(key) || is_text_key(key))
        key_wait_mode = KEY_WAIT_ALL;
    else
        key_wait_mode = KEY_WAIT_NONE;

    return (unsigned char)key;
}

static int sym_x_exit(void)
{
    return in_KeyPressed(0x4000) && in_KeyPressed(x_key_scancode);
}

static int contains(const char *haystack, const char *needle)
{
    return strstr(haystack, needle) != NULL;
}

static int is_ssh_control(const char *buf)
{
    return contains(buf, "CONNECTED") ||
           contains(buf, "TRUST?") ||
           contains(buf, "USER?") ||
           contains(buf, "PASSWORD?") ||
           contains(buf, "IDENTITY ") ||
           contains(buf, "ERROR ") ||
           contains(buf, "KEY-GENERATION");
}

static void print_bytes(const char *buf, int len)
{
    int i;

    for (i = 0; i < len; i++)
        putchar(buf[i]);
}

/* Hide underscore as a blank spacer; print cursor ends just past it. */
static void cursor_hide(void)
{
    if (!cursor_visible)
        return;

    putchar('\x08');
    putchar(' ');
    cursor_visible = 0;
    cursor_gap = 1;
}

/* Step onto the spacer, then draw underscore. */
static void cursor_show(void)
{
    if (cursor_visible)
        return;

    if (cursor_gap)
        putchar('\x08');

    putchar('_');
    cursor_visible = 1;
    cursor_gap = 0;
}

static void cursor_enable(void)
{
    cursor_active = 1;
    cursor_visible = 0;
    cursor_gap = 0;
    cursor_blink_tick = 0;
    cursor_show();
}

static void cursor_disable(void)
{
    if (!cursor_active)
        return;

    if (cursor_visible)
        cursor_hide();

    cursor_active = 0;
    cursor_visible = 0;
    cursor_gap = 0;
    cursor_blink_tick = 0;
}

/* Park on the blink spacer so the next printed byte replaces it. */
static void cursor_prepare_output(void)
{
    if (!cursor_active)
        return;

    if (cursor_visible)
        cursor_hide();

    if (cursor_gap)
        putchar('\x08');
}

static void cursor_finish_output(void)
{
    if (!cursor_active)
        return;

    cursor_gap = 0;
    cursor_show();
    cursor_blink_tick = 0;
}

static void cursor_toggle(void)
{
    if (cursor_visible)
        cursor_hide();
    else
        cursor_show();

    cursor_blink_tick = 0;
}

static void cursor_tick(void)
{
    if (!cursor_active)
        return;

    in_Wait(CURSOR_STEP_MS);

    if (++cursor_blink_tick < CURSOR_BLINK_TICKS)
        return;

    cursor_toggle();
}

static int read_line(char *buf, int maxlen)
{
    int pos = 0;
    int key;

    cursor_enable();

    while (1)
    {
        key = poll_key();
        if (key)
        {
            cursor_prepare_output();

            if (key == 13 || key == 10)
            {
                putchar('\n');
                buf[pos] = '\0';
                cursor_disable();
                return pos;
            }

            if (is_delete_key(key))
            {
                if (pos > 0)
                {
                    pos--;
                    printf("\x08 \x08");
                }
            }
            else if (pos < maxlen - 1 && key >= 32 && key < 127)
            {
                buf[pos++] = (char)key;
                putchar(key);
            }

            cursor_finish_output();
            continue;
        }

        cursor_tick();
    }
}

static void send_line(int sockfd, char *line)
{
    strcat(line, "\r\n");
    send(sockfd, line, strlen(line), 0);
}

static void print_trust_line(const char *buf)
{
    const char *p = strstr(buf, "TRUST?");

    if (!p)
        return;

    putchar('\n');
    while (*p && *p != '\r' && *p != '\n')
        putchar(*p++);
    putchar('\n');
}

static void print_identity_line(const char *line)
{
    const char *p;

    p = strstr(line, "IDENTITY ");
    if (!p)
        return;

    p += 9;
    putchar('\n');
    while (*p && *p != '\r' && *p != '\n')
        putchar(*p++);
    putchar('\n');
}

static int is_yes(const char *s)
{
    return s[0] == 'y' || s[0] == 'Y';
}

static void print_remote(const char *buf, int len)
{
    cursor_prepare_output();
    print_bytes(buf, len);
    cursor_finish_output();
}

static void ctrl_reset(void)
{
    ctrl_len = 0;
    ctrl_buf[0] = '\0';
}

static void ctrl_feed(const char *data, int len)
{
    int room;

    if (len <= 0)
        return;

    room = RXBUF_SIZE - 1 - ctrl_len;
    if (len > room)
        len = room;

    memcpy(ctrl_buf + ctrl_len, data, len);
    ctrl_len += len;
    ctrl_buf[ctrl_len] = '\0';
}

static void dispatch_control_line(int sockfd, char *line, char *linebuf)
{
    if (contains(line, "KEY-GENERATION"))
    {
        print_remote("SSH keypair is being generated...\n", 35);
        return;
    }

    if (contains(line, "IDENTITY "))
    {
        printf("\nShow ssh public key? (yes/no): ");
        read_line(linebuf, LINE_MAX);
        if (is_yes(linebuf))
        {
            cursor_prepare_output();
            print_identity_line(line);
            cursor_finish_output();
        }
        return;
    }

    if (contains(line, "TRUST?"))
    {
        print_trust_line(line);
        printf("Trust host key? (yes/no): ");
        read_line(linebuf, LINE_MAX);
        send_line(sockfd, linebuf);
        return;
    }

    if (contains(line, "USER?"))
    {
        printf("\nUsername: ");
        read_line(linebuf, LINE_MAX);
        send_line(sockfd, linebuf);
        return;
    }

    if (contains(line, "PASSWORD?"))
    {
        printf("\nPassword: ");
        read_line(linebuf, LINE_MAX);
        send_line(sockfd, linebuf);
        return;
    }

    if (contains(line, "CONNECTED"))
    {
        ssh_ready = 1;
        cursor_prepare_output();
        printf("\n--- SSH session ready (SYM+X to disconnect) ---\n");
        cursor_finish_output();
        cursor_enable();
        return;
    }

    if (contains(line, "ERROR "))
    {
        print_remote("\n", 1);
        print_remote(line, strlen(line));
        return;
    }

    if (line[0] != '\0')
        print_remote(line, strlen(line));
}

static void process_ctrl_lines(int sockfd, char *linebuf)
{
    char *eol;
    char *next;
    int consumed;

    while (ctrl_len > 0)
    {
        eol = NULL;
        for (next = ctrl_buf; next < ctrl_buf + ctrl_len; next++)
        {
            if (*next == '\n' || *next == '\r')
            {
                eol = next;
                break;
            }
        }

        if (!eol)
            break;

        *eol = '\0';
        dispatch_control_line(sockfd, ctrl_buf, linebuf);

        next = eol + 1;
        if (*eol == '\r' && next < ctrl_buf + ctrl_len && *next == '\n')
            next++;

        consumed = (int)(next - ctrl_buf);
        ctrl_len -= consumed;
        if (ctrl_len > 0)
            memmove(ctrl_buf, next, ctrl_len);
        ctrl_buf[ctrl_len] = '\0';
    }
}

static int poll_socket(int sockfd, struct pollfd *p, char *linebuf)
{
    int bytes;

    p->fd = sockfd;
    p->events = POLLIN;
    p->revents = poll_fd(sockfd);

    if (p->revents & POLLHUP)
    {
        cursor_disable();
        printf("\nRemote host disconnected.\n");
        return -1;
    }

    if (!(p->revents & POLLIN))
        return 0;

    bytes = recv(sockfd, rxbuf, RXBUF_SIZE - 1, 0);
    if (bytes < 0)
    {
        cursor_disable();
        printf("\nReceive failed.\n");
        return -1;
    }

    if (bytes == 0)
        return 0;

    rxbuf[bytes] = '\0';

    if (!ssh_ready || is_ssh_control(rxbuf))
    {
        ctrl_feed(rxbuf, bytes);
        process_ctrl_lines(sockfd, linebuf);
    }
    else
        print_remote(rxbuf, bytes);

    return 0;
}

static int terminal_send_key(int sockfd, int key)
{
    char ch;

    if (is_delete_key(key))
        ch = (char)SSH_BACKSPACE;
    else if (key == 13 || key == 10)
        ch = '\r';
    else
        ch = (char)key;

    if (send(sockfd, &ch, 1, 0) < 0)
    {
        cursor_disable();
        printf("\nSend failed.\n");
        return -1;
    }

    return 0;
}

static int handle_keyboard(int sockfd)
{
    int key;

    if (!ssh_ready)
        return 0;

    key = poll_key();
    if (!key)
        return 0;

    if (key < 32 && key != 13 && key != 10 && !is_delete_key(key))
        return 0;

    return terminal_send_key(sockfd, key);
}

static int connect_ssh(const char *host, int *sockfd_out)
{
    struct hostent *he;
    struct sockaddr_in addr;
    int sockfd;
    int rc;

    he = gethostbyname((char *)host);
    if (!he)
    {
        printf("DNS lookup failed for: %s\n", host);
        return 1;
    }

    sockfd = socket(AF_INET, SOCK_STREAM, 0);
    if (sockfd < 0)
    {
        printf("Could not open socket: %d\n", sockfd);
        return 1;
    }

    memset(&addr, 0, sizeof(addr));
    addr.sin_port = SSH_PORT;
    addr.sin_addr.s_addr = he->h_addr;

    printf("Connecting to %s:%d...\n", host, SSH_PORT);

    rc = connect(sockfd, &addr, sizeof(addr));
    if (rc == 0)
        printf("Connected.\n");
    else
        /* connect() may return before SSH auth finishes when prompts arrive. */
        printf("Waiting for SSH authentication...\n");

    *sockfd_out = sockfd;
    return 0;
}

static void session_reset(void)
{
    ssh_ready = 0;
    key_armed = 1;
    key_wait_mode = KEY_WAIT_NONE;
    ctrl_reset();
    cursor_disable();
}

static void disconnect_session(int *sockfd)
{
    if (*sockfd >= 0)
    {
        sockclose(*sockfd);
        *sockfd = -1;
    }

    session_reset();
}

static void session_loop(int sockfd)
{
    char linebuf[LINE_MAX];
    struct pollfd p;

    while (1)
    {
        if (sym_x_exit())
            break;

        if (poll_socket(sockfd, &p, linebuf) < 0)
            break;

        if (handle_keyboard(sockfd) < 0)
            break;

        cursor_tick();
    }
}

int main(void)
{
    char host[HOST_MAX];
    int sockfd = -1;

    x_key_scancode = in_LookupKey('x');

    pagein();

    putchar(12);
    printf("Spectranext SSH client\n");

    while (1)
    {
        printf("\nEnter server (user@host ok, empty to quit)\n: ");
        read_line(host, sizeof(host));

        if (host[0] == '\0')
            break;

        sockfd = -1;
        if (connect_ssh(host, &sockfd) != 0)
        {
            disconnect_session(&sockfd);
            continue;
        }

        session_loop(sockfd);
        disconnect_session(&sockfd);
        printf("\nDisconnected.\n");
    }

    printf("Done.\n");

    pageout();
    return 0;
}
