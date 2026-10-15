/* Peer-to-peer chat: the system handles discovery and connection setup. */
#include <stdio.h>
#include <string.h>
#include <input.h>
#include <netdb.h>
#include <sockpoll.h>
#include <spectranet.h>
#include <sys/socket.h>

#define SERVICE "p2p-chat@match.spx"
#define LINE_LENGTH 24

/* Both peers call this same blocking connection flow; neither listens. */
static int connect_peer(void)
{
    struct hostent *host;
    struct sockaddr_in address;
    int fd;

    host = gethostbyname(SERVICE);
    if (!host)
        return -1;
    memset(&address, 0, sizeof(address));
    address.sin_family = AF_INET;
    address.sin_addr.s_addr = host->h_addr;
    /* The match hostname selects the service; the application port is ignored. */
    fd = socket(AF_INET, SOCK_STREAM, 0);
    if (fd < 0)
        return -1;
    if (connect(fd, &address, sizeof(address)) < 0)
    {
        sockclose(fd);
        return -1;
    }
    return fd;
}

/* TCP writes may be partial. Send the whole line, including its newline. */
static int send_line(int fd, char *line, int length)
{
    int sent, offset = 0;
    line[length++] = '\n';
    while (offset < length)
    {
        sent = send(fd, line + offset, length - offset, 0);
        if (sent <= 0)
            return -1;
        offset += sent;
    }
    return 0;
}

/* Erase only the current prompt, preserving the conversation above it. */
static void erase_prompt(int length)
{
    int i;
    for (i = 0; i < length + 2; ++i)
        putchar('\x08');
    for (i = 0; i < length + 2; ++i)
        putchar(' ');
    for (i = 0; i < length + 2; ++i)
        putchar('\x08');
}

int main(void)
{
    char line[LINE_LENGTH + 2], incoming[LINE_LENGTH + 1], buffer[64];
    int fd, length = 0, received = 0, count, i, key, held = 0;
    unsigned char events;
    const char *reason = "Chat ended.";

    pagein();
    printf("\x0cPeer-to-peer chat\nOpening matchmaking...\n");
    fd = connect_peer();
    if (fd < 0)
    {
        printf("Not connected.\n");
        pageout();
        return 1;
    }

    printf("\x0cPeer-to-peer chat\nConnected!\nEnter: send  /quit: leave\n24 characters per message.\n\n> ");
    in_WaitForNoKey();
    for (;;)
    {
        events = poll_fd(fd);
        /* Drain final bytes before handling a simultaneous disconnect. */
        if (events & POLLIN)
        {
            count = recv(fd, buffer, sizeof(buffer), 0);
            if (count <= 0)
            {
                reason = "Peer disconnected.";
                break;
            }
            for (i = 0; i < count; ++i)
            {
                if (buffer[i] == '\n')
                {
                    incoming[received] = 0;
                    erase_prompt(length);
                    printf("Peer: %s\n> ", incoming);
                    line[length] = 0;
                    printf("%s", line);
                    received = 0;
                }
                else if (buffer[i] >= 32 && buffer[i] < 127 && received < LINE_LENGTH)
                    incoming[received++] = buffer[i];
            }
        }
        else if (events & (POLLHUP | POLLNVAL))
        {
            reason = "Peer disconnected.";
            break;
        }

        /* Debounce without blocking reception while a key is held. */
        key = in_Inkey();
        if (!key)
            held = 0;
        else if (!held)
        {
            held = 1;
            if (key == 13 || key == 10)
            {
                line[length] = 0;
                if (!strcmp(line, "/quit"))
                    break;
                if (length)
                {
                    erase_prompt(length);
                    printf("You: %s\n> ", line);
                    count = length;
                    length = 0;
                    if (send_line(fd, line, count) < 0)
                    {
                        reason = "Send failed.";
                        break;
                    }
                }
            }
            else if ((key == 8 || key == 12 || key == 127) && length)
            {
                --length;
                printf("\x08 \x08");
            }
            else if (key >= 32 && key < 127 && length < LINE_LENGTH)
            {
                line[length++] = key;
                putchar(key);
            }
        }
    }
    erase_prompt(length);
    printf("%s\n", reason);
    sockclose(fd);
    pageout();
    return 0;
}
