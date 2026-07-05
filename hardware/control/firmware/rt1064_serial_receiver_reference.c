/*
 * Reference RT1064 receiver for the smcar serial protocol.
 *
 * Copy the useful parts into a SeekFree RT1064 project such as:
 *   RT1064_Library-master/Example/Coreboard_Demo/E02_uart_demo
 *
 * Default debug UART wiring:
 *   UART_1 TX B12, RX B13, baud 115200
 *
 * Wireless UART option:
 *   UART_8 TX D16, RX D17, baud 115200
 *
 * PC sends one ASCII line per command:
 *   SMCAR,1,MOVE_TO,2,5\n
 *   SMCAR,2,ALIGN_TO_BOX,2,6,R\n
 *   SMCAR,3,PUSH_BOX,R,2\n
 *
 * Board replies:
 *   SMCAR,1,OK,message\n
 *   SMCAR,1,ERR,ERR_TIMEOUT,message\n
 */

#include "zf_common_headfile.h"

#include <stdlib.h>
#include <string.h>

#define SMCAR_UART_INDEX        (DEBUG_UART_INDEX)
#define SMCAR_UART_BAUDRATE     (DEBUG_UART_BAUDRATE)
#define SMCAR_UART_TX_PIN       (DEBUG_UART_TX_PIN)
#define SMCAR_UART_RX_PIN       (DEBUG_UART_RX_PIN)
#define SMCAR_UART_PRIORITY     (LPUART1_IRQn)

/*
 * To use the wireless UART module instead, replace the block above with:
 *
 * #define SMCAR_UART_INDEX     (UART_8)
 * #define SMCAR_UART_BAUDRATE  (115200)
 * #define SMCAR_UART_TX_PIN    (UART8_TX_D16)
 * #define SMCAR_UART_RX_PIN    (UART8_RX_D17)
 * #define SMCAR_UART_PRIORITY  (LPUART8_IRQn)
 *
 * Then call smcar_uart_rx_interrupt_handler() from LPUART8_IRQHandler().
 */

#define SMCAR_RX_FIFO_SIZE      (256)
#define SMCAR_LINE_SIZE         (96)

static fifo_struct smcar_rx_fifo;
static uint8 smcar_rx_storage[SMCAR_RX_FIFO_SIZE];
static uint8 smcar_rx_byte;

static char smcar_line[SMCAR_LINE_SIZE];
static uint32 smcar_line_len = 0;

static void smcar_send_ok(int seq, const char *message);
static void smcar_send_err(int seq, const char *code, const char *message);
static void smcar_process_line(char *line);
static int smcar_parse_int(const char *text, int *value);

static void vehicle_move_to(int row, int col);
static void vehicle_align_to_box(int row, int col, char direction);
static void vehicle_push_box(char direction, int cells);

int main(void)
{
    clock_init(SYSTEM_CLOCK_600M);

    fifo_init(&smcar_rx_fifo, FIFO_DATA_8BIT, smcar_rx_storage, SMCAR_RX_FIFO_SIZE);

    uart_init(SMCAR_UART_INDEX, SMCAR_UART_BAUDRATE, SMCAR_UART_TX_PIN, SMCAR_UART_RX_PIN);
    uart_rx_interrupt(SMCAR_UART_INDEX, ZF_ENABLE);
    interrupt_set_priority(SMCAR_UART_PRIORITY, 0);

    uart_write_string(SMCAR_UART_INDEX, "SMCAR,0,OK,rt1064 serial ready\r\n");

    while(1)
    {
        uint32 count = fifo_used(&smcar_rx_fifo);
        while(count--)
        {
            uint8 ch = 0;
            uint32 read_count = 1;
            fifo_read_buffer(&smcar_rx_fifo, &ch, &read_count, FIFO_READ_AND_CLEAN);

            if(ch == '\r')
            {
                continue;
            }

            if(ch == '\n')
            {
                smcar_line[smcar_line_len] = '\0';
                if(smcar_line_len > 0)
                {
                    smcar_process_line(smcar_line);
                }
                smcar_line_len = 0;
                continue;
            }

            if(smcar_line_len + 1 < SMCAR_LINE_SIZE)
            {
                smcar_line[smcar_line_len++] = (char)ch;
            }
            else
            {
                smcar_line_len = 0;
                smcar_send_err(0, "ERR_UNKNOWN", "line too long");
            }
        }

        system_delay_ms(1);
    }
}

void smcar_uart_rx_interrupt_handler(void)
{
    while(uart_query_byte(SMCAR_UART_INDEX, &smcar_rx_byte))
    {
        fifo_write_buffer(&smcar_rx_fifo, &smcar_rx_byte, 1);
    }
}

/*
 * In user/src/isr.c, call the handler from the matching UART IRQ:
 *
 * void LPUART1_IRQHandler(void)
 * {
 *     if(kLPUART_RxDataRegFullFlag & LPUART_GetStatusFlags(LPUART1))
 *     {
 *         extern void smcar_uart_rx_interrupt_handler(void);
 *         smcar_uart_rx_interrupt_handler();
 *     }
 *     LPUART_ClearStatusFlags(LPUART1, kLPUART_RxOverrunFlag);
 * }
 */

static void smcar_process_line(char *line)
{
    char *prefix = strtok(line, ",");
    char *seq_text = strtok(NULL, ",");
    char *command = strtok(NULL, ",");
    int seq = 0;

    if(prefix == NULL || strcmp(prefix, "SMCAR") != 0)
    {
        smcar_send_err(0, "ERR_UNKNOWN", "bad prefix");
        return;
    }

    if(seq_text == NULL || !smcar_parse_int(seq_text, &seq))
    {
        smcar_send_err(0, "ERR_UNKNOWN", "bad sequence");
        return;
    }

    if(command == NULL)
    {
        smcar_send_err(seq, "ERR_UNKNOWN", "missing command");
        return;
    }

    if(strcmp(command, "MOVE_TO") == 0)
    {
        char *row_text = strtok(NULL, ",");
        char *col_text = strtok(NULL, ",");
        int row = 0;
        int col = 0;
        if(!smcar_parse_int(row_text, &row) || !smcar_parse_int(col_text, &col))
        {
            smcar_send_err(seq, "ERR_UNKNOWN", "bad MOVE_TO args");
            return;
        }
        vehicle_move_to(row, col);
        smcar_send_ok(seq, "move_to accepted");
        return;
    }

    if(strcmp(command, "ALIGN_TO_BOX") == 0)
    {
        char *row_text = strtok(NULL, ",");
        char *col_text = strtok(NULL, ",");
        char *direction_text = strtok(NULL, ",");
        int row = 0;
        int col = 0;
        if(!smcar_parse_int(row_text, &row) || !smcar_parse_int(col_text, &col) ||
                direction_text == NULL || strlen(direction_text) != 1)
        {
            smcar_send_err(seq, "ERR_UNKNOWN", "bad ALIGN_TO_BOX args");
            return;
        }
        vehicle_align_to_box(row, col, direction_text[0]);
        smcar_send_ok(seq, "align_to_box accepted");
        return;
    }

    if(strcmp(command, "PUSH_BOX") == 0)
    {
        char *direction_text = strtok(NULL, ",");
        char *cells_text = strtok(NULL, ",");
        int cells = 0;
        if(direction_text == NULL || strlen(direction_text) != 1 || !smcar_parse_int(cells_text, &cells))
        {
            smcar_send_err(seq, "ERR_UNKNOWN", "bad PUSH_BOX args");
            return;
        }
        vehicle_push_box(direction_text[0], cells);
        smcar_send_ok(seq, "push_box accepted");
        return;
    }

    smcar_send_err(seq, "ERR_UNKNOWN", "unknown command");
}

static int smcar_parse_int(const char *text, int *value)
{
    char *end = NULL;
    long parsed = 0;

    if(text == NULL || *text == '\0')
    {
        return 0;
    }

    parsed = strtol(text, &end, 10);
    if(end == text || *end != '\0')
    {
        return 0;
    }

    *value = (int)parsed;
    return 1;
}

static void smcar_send_ok(int seq, const char *message)
{
    char buffer[96];
    sprintf(buffer, "SMCAR,%d,OK,%s\r\n", seq, message);
    uart_write_string(SMCAR_UART_INDEX, buffer);
}

static void smcar_send_err(int seq, const char *code, const char *message)
{
    char buffer[96];
    sprintf(buffer, "SMCAR,%d,ERR,%s,%s\r\n", seq, code, message);
    uart_write_string(SMCAR_UART_INDEX, buffer);
}

static void vehicle_move_to(int row, int col)
{
    /*
     * TODO: replace with chassis movement.
     * First hardware smoke test can leave this empty and only verify ACK.
     */
    (void)row;
    (void)col;
}

static void vehicle_align_to_box(int row, int col, char direction)
{
    (void)row;
    (void)col;
    (void)direction;
}

static void vehicle_push_box(char direction, int cells)
{
    (void)direction;
    (void)cells;
}
