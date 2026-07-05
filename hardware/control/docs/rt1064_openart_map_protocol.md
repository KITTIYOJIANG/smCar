# RT1064 OpenART Global Map Protocol

This note documents the UART frame used to send the projected global map from OpenART/camera-side code to the RT1064 chassis controller.

## Link

- UART: `UART_1`
- Baudrate: `115200`
- Default pins in firmware: `UART1_TX_B12`, `UART1_RX_B13`
- PC debug output: USB CDC virtual serial port

`debug_init()` is intentionally not called in `main.c`, because the SeekFree debug UART also uses UART1 by default.

## Frame Format

```text
0x5A 0xA5 CMD LEN DATA... CHECKSUM 0xED
```

Checksum:

```text
CHECKSUM = (CMD + LEN + sum(DATA bytes)) & 0xFF
```

## Global Map Frame

```text
CMD = 0x02
LEN = 195
```

Payload layout:

```text
data[0..191]   16 x 12 ASCII map, row-major order
data[192]      car direction char, for example U/D/L/R/N/E/S/W
data[193]      car column, x
data[194]      car row, y
```

The 16 x 12 map uses row-major order:

```text
index = row * 16 + col
```

## USB CDC Commands

After flashing the RT1064 firmware, connect the USB CDC serial port and use:

```text
map status      Print receiver status and latest car pose
map print       Print the latest cached 16 x 12 ASCII map
map stream 1    Print every valid received map frame
map stream 0    Stop auto-printing frames
```

Default behavior is cache-only. This avoids flooding the USB log when OpenART sends frames continuously.

## Test Flow

1. Keep the chassis lifted or stopped.
2. Connect OpenART TX/RX to RT1064 UART1 RX/TX and common GND.
3. Flash firmware.
4. Open USB CDC serial monitor.
5. Send `map status`.
6. Send a sample frame from OpenART or `tools/openart_map_frame.py`.
7. Send `map print` and verify the 16 x 12 ASCII map, car column, row, and direction.

