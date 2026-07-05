/*********************************************************************************************************************
* RT1064 wheel speed PI and four-wheel chassis test
*
* Purpose:
*   1. Use USB CDC virtual serial port for all commands and feedback.
*   2. Select one wheel at a time for speed-loop tuning, set four wheel targets together, or command chassis velocity.
*   3. Keep the motor duty strictly limited to +/-35%.
*
* Serial commands:
*   1              Start active wheel forward with current target speed.
*   q              Start active wheel backward with current target speed magnitude.
*   0 / s / S      Stop immediately.
*   z              Reset all encoder counts and PI integrals.
*   h / ?          Print help.
*   + / -          Increase/decrease target speed magnitude by 20 count/100ms.
*
*   wheel lb       Select active wheel: lb / rb / rf / lf. Selection stops all motors.
*   run            Start active wheel with current signed target speed.
*   runall         Start all four wheels with their current target speeds.
*   stop           Stop immediately.
*   reset          Reset all encoder counts and PI integrals.
*   status         Print current settings for all wheels.
*   target lb 200  Set one wheel target only; use run to start it.
*   targets a b c d Set LB/RB/RF/LF targets together and start all four wheels.
*   vel vx vy wz   Set chassis velocity in body frame and start all four wheels.
*   t 200          Set target speed to +200 count/100ms.
*   r 200          Set target speed to +200 and start.
*   b 200          Set target speed to -200 and start.
*   kp 0.020       Set Kp.
*   ki 0.002       Set Ki.
*   ff 1           Enable/disable speed feedforward.
*   ffbase 3.500   Set positive and negative feedforward base duty percent.
*   ffpos 3.500    Set positive feedforward base duty percent.
*   ffneg 3.500    Set negative feedforward base duty percent.
*   ffslope 0.016  Set feedforward slope duty percent per count/100ms.
*   boost 18.000   Set positive and negative stationary start boost duty percent.
*   boostpos 18.000 Set positive stationary start boost duty percent.
*   boostneg 18.000 Set negative stationary start boost duty percent.
*   imu status      Print IMU raw gyro/acc, yaw, offset and calibration state.
*   imu cal         Stop motors, calibrate gyro-z offset while the car is still, then reset yaw.
*   imu stream 1/0  Enable/disable periodic IMU yaw output.
*   imu sign 1/-1   Flip yaw sign if real CCW/right-turn direction is reversed.
*   yaw / yaw reset Print or reset integrated yaw.
*   turn 90         Turn left/CCW by 90 degrees with IMU yaw closed loop.
*   turn -90        Turn right/CW by 90 degrees with IMU yaw closed loop.
*   turn 180        Turn around with IMU yaw closed loop.
*   turn lvx -10    Set left/CCW turn vx compensation in mm/s.
*   turn lvy 10     Set left/CCW turn vy compensation in mm/s.
*   turn rvx -25    Set right/CW turn vx compensation in mm/s.
*   turn rvy 0      Set right/CW turn vy compensation in mm/s.
*   Body velocity units: vx right+, vy forward+, wz CCW+.
*
* Encoder wheel mapping on this car:
*   enc1 C0 / C1  : left rear  (LB)
*   enc2 C2 / C24 : right rear (RB)
*   enc3 C3 / C4  : right front(RF)
*   enc4 C5 / C25 : left front (LF)
*
* Manual forward-wheel encoder sign:
*   LB negative, RB positive, RF positive, LF negative.
* Therefore forward_count = raw_count * encoder_forward_sign.
*
* Manual forward-wheel motor sign:
*   LB negative PWM, RB positive PWM, RF positive PWM, LF negative PWM.
* Therefore raw_pwm = forward_duty * motor_forward_sign.
*
* Before motor testing, lift the car or keep the wheels off the ground.
********************************************************************************************************************/

#include "zf_common_headfile.h"

#define SAMPLE_PERIOD_MS              (100)
#define MOTOR_PWM_FREQ_HZ             (17000)

#define DUTY_LIMIT_PERCENT            (35)
#define DUTY_LIMIT_X1000              (DUTY_LIMIT_PERCENT * 1000)

#if (DUTY_LIMIT_PERCENT > 35)
#error "DUTY_LIMIT_PERCENT must never exceed 35"
#endif

#define DEFAULT_TARGET_SPEED          (0)      /* Boot safe: keep stored targets at idle until explicitly set. */
#define DEFAULT_START_TARGET_SPEED    (400)    /* Convenience start speed for 1/q shortcuts. */
#define TARGET_STEP_SPEED             (20)
#define TARGET_LIMIT_SPEED            (2000)

#define DEFAULT_KP_X1000              (6)      /* 0.006 duty_percent/count */
#define DEFAULT_KI_X1000              (1)      /* 0.001 duty_percent/count-sample */
#define DEFAULT_FF_ENABLE             (1)
#define DEFAULT_LB_FF_BASE_POS_X1000  (3500)   /* 3.500% */
#define DEFAULT_LB_FF_BASE_NEG_X1000  (3500)   /* 3.500% */
#define DEFAULT_RB_FF_BASE_POS_X1000  (4000)   /* 4.000% */
#define DEFAULT_RB_FF_BASE_NEG_X1000  (4000)   /* 4.000% */
#define DEFAULT_RF_FF_BASE_POS_X1000  (3000)   /* 3.000% */
#define DEFAULT_RF_FF_BASE_NEG_X1000  (3000)   /* 3.000% */
#define DEFAULT_LF_FF_BASE_POS_X1000  (3000)   /* 3.000% */
#define DEFAULT_LF_FF_BASE_NEG_X1000  (3000)   /* 3.000% */
#define DEFAULT_FF_SLOPE_X1000        (10)     /* 0.010% per count/100ms */
#define FF_SLOPE_LIMIT_X1000          (200)    /* 0.200% per count/100ms */
#define DEFAULT_LB_START_BOOST_POS_X1000 (0)
#define DEFAULT_LB_START_BOOST_NEG_X1000 (0)
#define DEFAULT_RB_START_BOOST_POS_X1000 (18000) /* RB measured high static drag. */
#define DEFAULT_RB_START_BOOST_NEG_X1000 (18000)
#define DEFAULT_RF_START_BOOST_POS_X1000 (0)
#define DEFAULT_RF_START_BOOST_NEG_X1000 (0)
#define DEFAULT_LF_START_BOOST_POS_X1000 (0)
#define DEFAULT_LF_START_BOOST_NEG_X1000 (0)
#define INTEGRAL_LIMIT_COUNT          (10000)

#define CHASSIS_HALF_LENGTH_MM        (100)
#define CHASSIS_HALF_WIDTH_MM         (90)
#define CHASSIS_ROTATION_ARM_MM       (CHASSIS_HALF_LENGTH_MM + CHASSIS_HALF_WIDTH_MM)
#define CHASSIS_MM_S_TO_TARGET_X1000  (1206)   /* Measured 2386.7 count/wheel-rev, 63 mm wheel diameter. */
#define CHASSIS_DEG_S_TO_TARGET_X1000 (3999)   /* O-rectangle yaw term with CHASSIS_ROTATION_ARM_MM = 190 mm. */

#define ENCODER_DEADBAND_COUNT        (2)
#define RX_LINE_MAX                   (64)

#define IMU_GYRO_FACTOR_X1000         (14300)  /* raw / 14.3 = deg/s in default +/-2000 dps range. */
#define IMU_CAL_SAMPLE_COUNT          (200)
#define IMU_CAL_SAMPLE_INTERVAL_MS    (5)
#define IMU_CAL_STABLE_RANGE_LIMIT    (80)
#define IMU_YAW_SIGN_DEFAULT          (-1)     /* User test: left/CCW hand turn produced negative raw gyro-z. */
#define IMU_STREAM_PERIOD_TICKS       (2)

#define TURN_DEFAULT_KP_X1000         (1500)   /* wz deg/s = yaw error deg * 1.500 */
#define TURN_DEFAULT_MAX_WZ_DEG_S     (150)    /* Tuned with the serial turn GUI. */
#define TURN_DEFAULT_MIN_WZ_DEG_S     (120)
#define TURN_DEFAULT_STOP_ERROR_X1000 (2000)   /* Stop after staying within +/-2.0 deg. */
#define TURN_STABLE_TICKS             (4)
#define TURN_STATUS_PERIOD_TICKS      (2)
#define TURN_ANGLE_LIMIT_DEG          (360)
#define TURN_COMP_LIMIT_MM_S          (120)
#define TURN_LEFT_COMP_VX_DEFAULT_MM_S  (-10)  /* 2026-07-05 floor test: left 90 deg center drift <= 2 cm. */
#define TURN_LEFT_COMP_VY_DEFAULT_MM_S  (10)
#define TURN_RIGHT_COMP_VX_DEFAULT_MM_S (-25)  /* 2026-07-05 floor test: right 90 deg used stronger left compensation. */
#define TURN_RIGHT_COMP_VY_DEFAULT_MM_S (0)

#define MOTOR_1_DIR                   (C9 )
#define MOTOR_1_PWM                   (PWM2_MODULE1_CHA_C8)

#define MOTOR_2_DIR                   (C7 )
#define MOTOR_2_PWM                   (PWM2_MODULE0_CHA_C6)

#define MOTOR_3_DIR                   (D2 )
#define MOTOR_3_PWM                   (PWM2_MODULE3_CHB_D3)

#define MOTOR_4_DIR                   (C10 )
#define MOTOR_4_PWM                   (PWM2_MODULE2_CHB_C11)

#define ENCODER_1                     (QTIMER1_ENCODER1)
#define ENCODER_1_LSB                 (QTIMER1_ENCODER1_CH1_C0)
#define ENCODER_1_DIR                 (QTIMER1_ENCODER1_CH2_C1)

#define ENCODER_2                     (QTIMER1_ENCODER2)
#define ENCODER_2_LSB                 (QTIMER1_ENCODER2_CH1_C2)
#define ENCODER_2_DIR                 (QTIMER1_ENCODER2_CH2_C24)

#define ENCODER_3                     (QTIMER2_ENCODER1)
#define ENCODER_3_LSB                 (QTIMER2_ENCODER1_CH1_C3)
#define ENCODER_3_DIR                 (QTIMER2_ENCODER1_CH2_C4)

#define ENCODER_4                     (QTIMER2_ENCODER2)
#define ENCODER_4_LSB                 (QTIMER2_ENCODER2_CH1_C5)
#define ENCODER_4_DIR                 (QTIMER2_ENCODER2_CH2_C25)

typedef enum
{
    WHEEL_LB = 0,
    WHEEL_RB,
    WHEEL_RF,
    WHEEL_LF,
    WHEEL_COUNT,
} wheel_index_enum;

typedef struct
{
    const char *name;
    const char *encoder_pins;
    pwm_channel_enum motor_pwm;
    gpio_pin_enum motor_dir;
    encoder_index_enum encoder;
    encoder_channel1_enum encoder_lsb;
    encoder_channel2_enum encoder_dir;
    int8 encoder_forward_sign;
    int8 motor_forward_sign;
} wheel_config_struct;

typedef struct
{
    int16 target_speed;
    int32 kp_x1000;
    int32 ki_x1000;
    int32 ff_base_pos_x1000;
    int32 ff_base_neg_x1000;
    int32 ff_slope_x1000;
    int32 start_boost_pos_x1000;
    int32 start_boost_neg_x1000;
    int32 integral;
    int32 duty_x1000;
    uint8 enabled;
    uint8 ff_enabled;
} wheel_pi_struct;

typedef enum
{
    CHASSIS_MODE_MANUAL = 0,
    CHASSIS_MODE_VEL,
} chassis_mode_enum;

static const wheel_config_struct wheel_table[WHEEL_COUNT] =
{
    {"LB", "C0/C1",  MOTOR_2_PWM, MOTOR_2_DIR, ENCODER_1, ENCODER_1_LSB, ENCODER_1_DIR, -1, -1},
    {"RB", "C2/C24", MOTOR_1_PWM, MOTOR_1_DIR, ENCODER_2, ENCODER_2_LSB, ENCODER_2_DIR,  1,  1},
    {"RF", "C3/C4",  MOTOR_3_PWM, MOTOR_3_DIR, ENCODER_3, ENCODER_3_LSB, ENCODER_3_DIR,  1,  1},
    {"LF", "C5/C25", MOTOR_4_PWM, MOTOR_4_DIR, ENCODER_4, ENCODER_4_LSB, ENCODER_4_DIR, -1, -1},
};

#define WHEEL_PI_DEFAULT(ff_base_pos_x1000, ff_base_neg_x1000, start_boost_pos_x1000, start_boost_neg_x1000) \
    {DEFAULT_TARGET_SPEED, DEFAULT_KP_X1000, DEFAULT_KI_X1000, (ff_base_pos_x1000), (ff_base_neg_x1000), DEFAULT_FF_SLOPE_X1000, (start_boost_pos_x1000), (start_boost_neg_x1000), 0, 0, 0, DEFAULT_FF_ENABLE}

static wheel_pi_struct wheel_pi[WHEEL_COUNT] =
{
    WHEEL_PI_DEFAULT(DEFAULT_LB_FF_BASE_POS_X1000, DEFAULT_LB_FF_BASE_NEG_X1000, DEFAULT_LB_START_BOOST_POS_X1000, DEFAULT_LB_START_BOOST_NEG_X1000),
    WHEEL_PI_DEFAULT(DEFAULT_RB_FF_BASE_POS_X1000, DEFAULT_RB_FF_BASE_NEG_X1000, DEFAULT_RB_START_BOOST_POS_X1000, DEFAULT_RB_START_BOOST_NEG_X1000),
    WHEEL_PI_DEFAULT(DEFAULT_RF_FF_BASE_POS_X1000, DEFAULT_RF_FF_BASE_NEG_X1000, DEFAULT_RF_START_BOOST_POS_X1000, DEFAULT_RF_START_BOOST_NEG_X1000),
    WHEEL_PI_DEFAULT(DEFAULT_LF_FF_BASE_POS_X1000, DEFAULT_LF_FF_BASE_NEG_X1000, DEFAULT_LF_START_BOOST_POS_X1000, DEFAULT_LF_START_BOOST_NEG_X1000),
};

static wheel_index_enum active_wheel = WHEEL_LB;
static chassis_mode_enum chassis_mode = CHASSIS_MODE_MANUAL;
static int16 chassis_velocity_vx_mm_s = 0;
static int16 chassis_velocity_vy_mm_s = 0;
static int16 chassis_velocity_wz_deg_s = 0;

volatile uint8 chassis_stop_request = 0;
volatile uint8 chassis_reset_request = 0;
volatile uint8 chassis_help_request = 0;
volatile uint8 chassis_short_command = 0;
volatile uint8 chassis_line_ready = 0;

static char chassis_line_buffer[RX_LINE_MAX];
static char chassis_rx_line[RX_LINE_MAX];
static volatile uint8 chassis_rx_line_len = 0;

static uint8 imu_ready = 0;
static uint8 imu_calibrated = 0;
static uint8 imu_stream_enabled = 0;
static uint8 imu_stream_counter = 0;
static int8 imu_yaw_sign = IMU_YAW_SIGN_DEFAULT;
static int32 imu_gyro_z_offset_x1000 = 0;
static int32 imu_gyro_z_dps_x1000 = 0;
static int32 imu_yaw_deg_x1000 = 0;

static uint8 turn_active = 0;
static uint8 turn_stable_ticks = 0;
static uint8 turn_status_counter = 0;
static int16 turn_last_wz_deg_s = 0;
static int16 turn_max_wz_deg_s = TURN_DEFAULT_MAX_WZ_DEG_S;
static int16 turn_min_wz_deg_s = TURN_DEFAULT_MIN_WZ_DEG_S;
static int16 turn_left_comp_vx_mm_s = TURN_LEFT_COMP_VX_DEFAULT_MM_S;
static int16 turn_left_comp_vy_mm_s = TURN_LEFT_COMP_VY_DEFAULT_MM_S;
static int16 turn_right_comp_vx_mm_s = TURN_RIGHT_COMP_VX_DEFAULT_MM_S;
static int16 turn_right_comp_vy_mm_s = TURN_RIGHT_COMP_VY_DEFAULT_MM_S;
static int32 turn_kp_x1000 = TURN_DEFAULT_KP_X1000;
static int32 turn_stop_error_x1000 = TURN_DEFAULT_STOP_ERROR_X1000;
static int32 turn_target_yaw_x1000 = 0;

static void chassis_stop(void);
static uint8 chassis_apply_velocity_targets(int16 vx_mm_s, int16 vy_mm_s, int16 wz_deg_s);

static int32 abs_i32(int32 value)
{
    return (value < 0) ? -value : value;
}

static int16 abs_i16(int16 value)
{
    return (value < 0) ? -value : value;
}

static int32 clamp_i32(int32 value, int32 min_value, int32 max_value)
{
    if(value > max_value)
    {
        value = max_value;
    }
    else if(value < min_value)
    {
        value = min_value;
    }

    return value;
}

static int16 clamp_i16(int32 value, int16 min_value, int16 max_value)
{
    if(value > max_value)
    {
        value = max_value;
    }
    else if(value < min_value)
    {
        value = min_value;
    }

    return (int16)value;
}

static char lower_char(char value)
{
    if(('A' <= value) && (value <= 'Z'))
    {
        value = value - 'A' + 'a';
    }

    return value;
}

static uint8 is_space_char(char value)
{
    return ((' ' == value) || ('\t' == value));
}

static uint8 is_digit_char(char value)
{
    return (('0' <= value) && (value <= '9'));
}

static const char *skip_spaces(const char *str)
{
    while(is_space_char(*str))
    {
        str ++;
    }

    return str;
}

static const char *skip_value_separators(const char *str)
{
    while(is_space_char(*str) || (',' == *str))
    {
        str ++;
    }

    return str;
}

static uint8 command_name_match(const char *line, const char *name)
{
    uint8 i = 0;

    line = skip_spaces(line);

    while(name[i])
    {
        if(lower_char(line[i]) != name[i])
        {
            return 0;
        }
        i ++;
    }

    return (('\0' == line[i]) || is_space_char(line[i]) || ('=' == line[i]));
}

static const char *command_argument(const char *line)
{
    line = skip_spaces(line);
    while(('\0' != *line) && !is_space_char(*line) && ('=' != *line))
    {
        line ++;
    }
    while(is_space_char(*line) || ('=' == *line))
    {
        line ++;
    }

    return line;
}

static uint8 parse_int16_value_from(const char **str, int16 *value)
{
    int32 result = 0;
    int8 sign = 1;
    uint8 digit_found = 0;
    const char *cursor;

    cursor = skip_value_separators(*str);

    if('-' == *cursor)
    {
        sign = -1;
        cursor ++;
    }
    else if('+' == *cursor)
    {
        cursor ++;
    }

    while(is_digit_char(*cursor))
    {
        digit_found = 1;
        result = result * 10 + (*cursor - '0');
        cursor ++;
    }

    if(!digit_found)
    {
        return 1;
    }

    result *= sign;
    *value = clamp_i16(result, -TARGET_LIMIT_SPEED, TARGET_LIMIT_SPEED);
    *str = cursor;
    return 0;
}

static uint8 parse_int16_value(const char *str, int16 *value)
{
    return parse_int16_value_from(&str, value);
}

static uint8 parse_four_int16_values(const char *str, int16 values[WHEEL_COUNT])
{
    uint8 i;

    for(i = 0; i < WHEEL_COUNT; i ++)
    {
        if(0 != parse_int16_value_from(&str, &values[i]))
        {
            return 1;
        }
    }

    str = skip_value_separators(str);
    return ('\0' == *str) ? 0 : 1;
}

static uint8 parse_three_int16_values(const char *str, int16 values[3])
{
    uint8 i;

    for(i = 0; i < 3; i ++)
    {
        if(0 != parse_int16_value_from(&str, &values[i]))
        {
            return 1;
        }
    }

    str = skip_value_separators(str);
    return ('\0' == *str) ? 0 : 1;
}

static int32 round_i64_div(int64 value, int32 divisor)
{
    int64 half;

    if(divisor <= 0)
    {
        return 0;
    }

    half = divisor / 2;
    if(value >= 0)
    {
        return (int32)((value + half) / divisor);
    }

    return (int32)(-(((-value) + half) / divisor));
}

static int32 round_i64_div_1000(int64 value)
{
    return round_i64_div(value, 1000);
}

static int16 chassis_velocity_target_from_x1000(int64 value_x1000, uint8 *limited)
{
    int32 target;

    target = round_i64_div_1000(value_x1000);
    if(target > TARGET_LIMIT_SPEED)
    {
        target = TARGET_LIMIT_SPEED;
        *limited = 1;
    }
    else if(target < -TARGET_LIMIT_SPEED)
    {
        target = -TARGET_LIMIT_SPEED;
        *limited = 1;
    }

    return (int16)target;
}

/* PDF inverse kinematics for the O-rectangle chassis: x right+, y forward+, yaw CCW+. */
static uint8 chassis_velocity_to_targets(int16 vx_mm_s, int16 vy_mm_s, int16 wz_deg_s, int16 targets[WHEEL_COUNT])
{
    int64 vx_term_x1000;
    int64 vy_term_x1000;
    int64 wz_term_x1000;
    uint8 limited;

    limited = 0;
    vx_term_x1000 = (int64)vx_mm_s * CHASSIS_MM_S_TO_TARGET_X1000;
    vy_term_x1000 = (int64)vy_mm_s * CHASSIS_MM_S_TO_TARGET_X1000;
    wz_term_x1000 = (int64)wz_deg_s * CHASSIS_DEG_S_TO_TARGET_X1000;

    targets[WHEEL_LB] = chassis_velocity_target_from_x1000(vy_term_x1000 - vx_term_x1000 - wz_term_x1000, &limited);
    targets[WHEEL_RB] = chassis_velocity_target_from_x1000(vy_term_x1000 + vx_term_x1000 + wz_term_x1000, &limited);
    targets[WHEEL_RF] = chassis_velocity_target_from_x1000(vy_term_x1000 - vx_term_x1000 + wz_term_x1000, &limited);
    targets[WHEEL_LF] = chassis_velocity_target_from_x1000(vy_term_x1000 + vx_term_x1000 - wz_term_x1000, &limited);

    return limited;
}

static void turn_control_clear(void)
{
    turn_active = 0;
    turn_stable_ticks = 0;
    turn_status_counter = 0;
    turn_last_wz_deg_s = 0;
}

static void chassis_motion_clear(void)
{
    turn_control_clear();
    chassis_mode = CHASSIS_MODE_MANUAL;
    chassis_velocity_vx_mm_s = 0;
    chassis_velocity_vy_mm_s = 0;
    chassis_velocity_wz_deg_s = 0;
}

static void chassis_motion_set_velocity(int16 vx_mm_s, int16 vy_mm_s, int16 wz_deg_s)
{
    chassis_mode = CHASSIS_MODE_VEL;
    chassis_velocity_vx_mm_s = vx_mm_s;
    chassis_velocity_vy_mm_s = vy_mm_s;
    chassis_velocity_wz_deg_s = wz_deg_s;
}

static uint8 parse_scaled_1000(const char *str, int32 *value)
{
    int32 integer = 0;
    int32 fraction = 0;
    int8 sign = 1;
    uint8 digit_found = 0;
    uint8 fraction_digits = 0;

    str = skip_spaces(str);

    if('-' == *str)
    {
        sign = -1;
        str ++;
    }
    else if('+' == *str)
    {
        str ++;
    }

    while(is_digit_char(*str))
    {
        digit_found = 1;
        integer = integer * 10 + (*str - '0');
        str ++;
    }

    if('.' == *str)
    {
        str ++;
        while(is_digit_char(*str))
        {
            digit_found = 1;
            if(fraction_digits < 3)
            {
                fraction = fraction * 10 + (*str - '0');
                fraction_digits ++;
            }
            str ++;
        }
    }

    if(!digit_found)
    {
        return 1;
    }

    while(fraction_digits < 3)
    {
        fraction *= 10;
        fraction_digits ++;
    }

    *value = sign * (integer * 1000 + fraction);
    return 0;
}

static uint8 parse_wheel_index(const char *str, wheel_index_enum *wheel)
{
    char c0;
    char c1;

    str = skip_spaces(str);
    c0 = lower_char(str[0]);
    c1 = lower_char(str[1]);

    if(('l' == c0) && ('b' == c1))
    {
        *wheel = WHEEL_LB;
        return 0;
    }
    if(('r' == c0) && ('b' == c1))
    {
        *wheel = WHEEL_RB;
        return 0;
    }
    if(('r' == c0) && ('f' == c1))
    {
        *wheel = WHEEL_RF;
        return 0;
    }
    if(('l' == c0) && ('f' == c1))
    {
        *wheel = WHEEL_LF;
        return 0;
    }

    return 1;
}

static void line_submit_from_rx_buffer(void)
{
    uint8 i;

    if((0 == chassis_rx_line_len) || chassis_line_ready)
    {
        chassis_rx_line_len = 0;
        return;
    }

    for(i = 0; i < chassis_rx_line_len; i ++)
    {
        chassis_line_buffer[i] = chassis_rx_line[i];
    }
    chassis_line_buffer[chassis_rx_line_len] = '\0';
    chassis_rx_line_len = 0;
    chassis_line_ready = 1;
}

/* Feed multi-byte CDC packets byte-by-byte so newline-delimited commands stay intact. */
static void line_submit_from_packet(const uint8 *buffer, uint32 length)
{
    uint32 i;
    uint8 data;

    if(chassis_line_ready)
    {
        return;
    }

    for(i = 0; i < length; i ++)
    {
        data = buffer[i];
        if(('\r' == data) || ('\n' == data))
        {
            line_submit_from_rx_buffer();
            if(chassis_line_ready)
            {
                break;
            }
        }
        else if((32 <= data) && (data <= 126))
        {
            if(chassis_rx_line_len < (RX_LINE_MAX - 1))
            {
                chassis_rx_line[chassis_rx_line_len] = (char)data;
                chassis_rx_line_len ++;
            }
        }
    }
}

void usb_cdc_user_receive_callback(const uint8 *buffer, uint32 length)
{
    uint8 data;

    if(0 == length)
    {
        return;
    }

    if((1 == length) && (0 == chassis_rx_line_len) && (0 == chassis_line_ready))
    {
        data = buffer[0];
        if(('0' == data) || ('s' == data) || ('S' == data))
        {
            chassis_stop_request = 1;
            chassis_rx_line_len = 0;
            return;
        }
        if(('z' == data) || ('Z' == data))
        {
            chassis_reset_request = 1;
            chassis_rx_line_len = 0;
            return;
        }
        if(('h' == data) || ('H' == data) || ('?' == data))
        {
            chassis_help_request = 1;
            chassis_rx_line_len = 0;
            return;
        }
        if(('1' == data) || ('q' == data) || ('Q' == data) || ('+' == data) || ('-' == data))
        {
            chassis_short_command = data;
            chassis_rx_line_len = 0;
            return;
        }
    }

    line_submit_from_packet(buffer, length);
}

static void motor_pwm_set_x1000(pwm_channel_enum pwm_pin, gpio_pin_enum dir_pin, int32 duty_x1000)
{
    uint32 duty_value;

    duty_x1000 = clamp_i32(duty_x1000, -DUTY_LIMIT_X1000, DUTY_LIMIT_X1000);

    if(duty_x1000 >= 0)
    {
        gpio_set_level(dir_pin, GPIO_HIGH);
        duty_value = (uint32)duty_x1000 * PWM_DUTY_MAX / 100000;
    }
    else
    {
        gpio_set_level(dir_pin, GPIO_LOW);
        duty_value = (uint32)(-duty_x1000) * PWM_DUTY_MAX / 100000;
    }

    pwm_set_duty(pwm_pin, duty_value);
}

static void motor_init_all(void)
{
    uint8 i;

    for(i = 0; i < WHEEL_COUNT; i ++)
    {
        gpio_init(wheel_table[i].motor_dir, GPO, GPIO_HIGH, GPO_PUSH_PULL);
        pwm_init(wheel_table[i].motor_pwm, MOTOR_PWM_FREQ_HZ, 0);
    }
}

static void motor_stop_all(void)
{
    uint8 i;

    for(i = 0; i < WHEEL_COUNT; i ++)
    {
        motor_pwm_set_x1000(wheel_table[i].motor_pwm, wheel_table[i].motor_dir, 0);
    }
}

static void motor_set_forward_duty_x1000(wheel_index_enum wheel, int32 forward_duty_x1000)
{
    int32 raw_duty_x1000;

    forward_duty_x1000 = clamp_i32(forward_duty_x1000, -DUTY_LIMIT_X1000, DUTY_LIMIT_X1000);
    raw_duty_x1000 = forward_duty_x1000 * wheel_table[wheel].motor_forward_sign;
    motor_pwm_set_x1000(wheel_table[wheel].motor_pwm, wheel_table[wheel].motor_dir, raw_duty_x1000);
}

static void encoder_init_all(void)
{
    uint8 i;

    for(i = 0; i < WHEEL_COUNT; i ++)
    {
        encoder_dir_init(wheel_table[i].encoder, wheel_table[i].encoder_lsb, wheel_table[i].encoder_dir);
        encoder_clear_count(wheel_table[i].encoder);
    }
}

static void encoder_clear_all(void)
{
    uint8 i;

    for(i = 0; i < WHEEL_COUNT; i ++)
    {
        encoder_clear_count(wheel_table[i].encoder);
    }
}

static int16 encoder_read_forward_count(wheel_index_enum wheel)
{
    int16 raw_count;
    int16 forward_count;

    raw_count = encoder_get_count(wheel_table[wheel].encoder);
    encoder_clear_count(wheel_table[wheel].encoder);

    forward_count = raw_count * wheel_table[wheel].encoder_forward_sign;
    if(abs_i16(forward_count) <= ENCODER_DEADBAND_COUNT)
    {
        forward_count = 0;
    }

    return forward_count;
}

static void wheel_pi_reset(wheel_index_enum wheel)
{
    wheel_pi[wheel].integral = 0;
    wheel_pi[wheel].duty_x1000 = 0;
}

static void wheel_pi_reset_all(void)
{
    uint8 i;

    for(i = 0; i < WHEEL_COUNT; i ++)
    {
        wheel_pi_reset((wheel_index_enum)i);
    }
}

static void wheel_set_target_raw(wheel_index_enum wheel, int16 target_speed)
{
    wheel_pi[wheel].target_speed = clamp_i16(target_speed, -TARGET_LIMIT_SPEED, TARGET_LIMIT_SPEED);
    chassis_motion_clear();
}

static void wheel_set_target_keep_motion(wheel_index_enum wheel, int16 target_speed)
{
    wheel_pi[wheel].target_speed = clamp_i16(target_speed, -TARGET_LIMIT_SPEED, TARGET_LIMIT_SPEED);
}

static int32 wheel_feedforward_x1000(const wheel_pi_struct *pi)
{
    int32 magnitude;
    int32 duty_x1000;

    if((0 == pi->ff_enabled) || (0 == pi->target_speed))
    {
        return 0;
    }

    magnitude = abs_i16(pi->target_speed);
    duty_x1000 = ((pi->target_speed < 0) ? pi->ff_base_neg_x1000 : pi->ff_base_pos_x1000)
            + pi->ff_slope_x1000 * magnitude;
    duty_x1000 = clamp_i32(duty_x1000, 0, DUTY_LIMIT_X1000);

    return (pi->target_speed < 0) ? -duty_x1000 : duty_x1000;
}

static int32 wheel_start_boost_x1000(const wheel_pi_struct *pi, int16 measured_speed)
{
    if((0 == pi->target_speed) || (abs_i16(measured_speed) > ENCODER_DEADBAND_COUNT))
    {
        return 0;
    }

    return (pi->target_speed < 0) ? -pi->start_boost_neg_x1000 : pi->start_boost_pos_x1000;
}

static int32 wheel_pi_update(wheel_index_enum wheel, int16 measured_speed)
{
    wheel_pi_struct *pi;
    int32 error;
    int32 ff_duty;
    int32 boost_duty;
    int32 integral_candidate;
    int32 duty_candidate;
    int32 duty_limited;

    pi = &wheel_pi[wheel];
    error = (int32)pi->target_speed - measured_speed;
    ff_duty = wheel_feedforward_x1000(pi);
    integral_candidate = pi->integral + error;
    integral_candidate = clamp_i32(integral_candidate, -INTEGRAL_LIMIT_COUNT, INTEGRAL_LIMIT_COUNT);

    duty_candidate = ff_duty + pi->kp_x1000 * error + pi->ki_x1000 * integral_candidate;
    duty_limited = clamp_i32(duty_candidate, -DUTY_LIMIT_X1000, DUTY_LIMIT_X1000);

    if(((duty_limited >= DUTY_LIMIT_X1000) && (error > 0)) ||
       ((duty_limited <= -DUTY_LIMIT_X1000) && (error < 0)))
    {
        duty_candidate = ff_duty + pi->kp_x1000 * error + pi->ki_x1000 * pi->integral;
        duty_limited = clamp_i32(duty_candidate, -DUTY_LIMIT_X1000, DUTY_LIMIT_X1000);
    }
    else
    {
        pi->integral = integral_candidate;
    }

    if(((pi->target_speed > 0) && (duty_limited < 0)) ||
       ((pi->target_speed < 0) && (duty_limited > 0)))
    {
        duty_limited = 0;
    }

    boost_duty = wheel_start_boost_x1000(pi, measured_speed);
    if((boost_duty > 0) && (duty_limited < boost_duty))
    {
        duty_limited = boost_duty;
    }
    else if((boost_duty < 0) && (duty_limited > boost_duty))
    {
        duty_limited = boost_duty;
    }
    duty_limited = clamp_i32(duty_limited, -DUTY_LIMIT_X1000, DUTY_LIMIT_X1000);

    pi->duty_x1000 = duty_limited;
    return duty_limited;
}

static void print_scaled_value(int32 value)
{
    char text_buf[32];
    int32 value_abs;

    value_abs = abs_i32(value);
    snprintf(text_buf, sizeof(text_buf), "%c%ld.%03ld",
            (value < 0) ? '-' : '+',
            (long)(value_abs / 1000),
            (long)(value_abs % 1000));
    usb_cdc_write_string(text_buf);
}

static void imu_yaw_reset(void)
{
    imu_yaw_deg_x1000 = 0;
}

static void imu_update(void)
{
    int32 corrected_raw_x1000;

    if(!imu_ready)
    {
        return;
    }

    imu660rb_get_acc();
    imu660rb_get_gyro();

    if(!imu_calibrated)
    {
        imu_gyro_z_dps_x1000 = 0;
        return;
    }

    corrected_raw_x1000 = (int32)imu660rb_gyro_z * 1000 - imu_gyro_z_offset_x1000;
    imu_gyro_z_dps_x1000 = round_i64_div((int64)corrected_raw_x1000 * 1000, IMU_GYRO_FACTOR_X1000);
    imu_gyro_z_dps_x1000 *= imu_yaw_sign;
    imu_yaw_deg_x1000 += round_i64_div((int64)imu_gyro_z_dps_x1000 * SAMPLE_PERIOD_MS, 1000);
}

static void imu_init_device(void)
{
    imu_ready = (0 == imu660rb_init()) ? 1 : 0;
    imu_calibrated = 0;
    imu_stream_enabled = 0;
    imu_stream_counter = 0;
    imu_gyro_z_offset_x1000 = 0;
    imu_gyro_z_dps_x1000 = 0;
    imu_yaw_deg_x1000 = 0;

    if(imu_ready)
    {
        imu660rb_get_acc();
        imu660rb_get_gyro();
        usb_cdc_write_string("IMU660RB init ok. Send 'imu cal' while car is still before using yaw.\r\n");
    }
    else
    {
        usb_cdc_write_string("IMU660RB init error. Motor/chassis commands still work; use 'imu init' to retry.\r\n");
    }
}

static void imu_calibrate_gyro_z(void)
{
    uint16 i;
    int64 sum;
    int16 min_z;
    int16 max_z;
    char text_buf[120];

    if(!imu_ready)
    {
        usb_cdc_write_string("IMU not ready. Check SPI C20-C23 wiring, then send 'imu init'.\r\n");
        return;
    }

    usb_cdc_write_string("IMU gyro-z calibration start. Keep the car completely still...\r\n");
    system_delay_ms(100);

    sum = 0;
    min_z = 32767;
    max_z = -32768;

    for(i = 0; i < IMU_CAL_SAMPLE_COUNT; i ++)
    {
        imu660rb_get_gyro();
        sum += imu660rb_gyro_z;
        if(imu660rb_gyro_z < min_z)
        {
            min_z = imu660rb_gyro_z;
        }
        if(imu660rb_gyro_z > max_z)
        {
            max_z = imu660rb_gyro_z;
        }
        system_delay_ms(IMU_CAL_SAMPLE_INTERVAL_MS);
    }

    imu_gyro_z_offset_x1000 = (int32)((sum * 1000) / IMU_CAL_SAMPLE_COUNT);
    imu_calibrated = 1;
    imu_gyro_z_dps_x1000 = 0;
    imu_yaw_reset();
    imu_update();

    usb_cdc_write_string("IMU gyro-z calibration done. offset_raw=");
    print_scaled_value(imu_gyro_z_offset_x1000);
    snprintf(text_buf, sizeof(text_buf), " range=%d yaw reset to 0 deg\r\n", (int)(max_z - min_z));
    usb_cdc_write_string(text_buf);

    if((max_z - min_z) > IMU_CAL_STABLE_RANGE_LIMIT)
    {
        usb_cdc_write_string("Warning: gyro-z moved during calibration. Put the car still and run 'imu cal' again if yaw drifts.\r\n");
    }
}

static void print_imu_status(void)
{
    char text_buf[200];

    snprintf(text_buf, sizeof(text_buf),
            "imu: ready=%d calibrated=%d sign=%d stream=%d raw_acc=(%d,%d,%d) raw_gyro=(%d,%d,%d)\r\n",
            imu_ready,
            imu_calibrated,
            imu_yaw_sign,
            imu_stream_enabled,
            imu660rb_acc_x,
            imu660rb_acc_y,
            imu660rb_acc_z,
            imu660rb_gyro_x,
            imu660rb_gyro_y,
            imu660rb_gyro_z);
    usb_cdc_write_string(text_buf);

    usb_cdc_write_string("imu: gyro_z_offset_raw=");
    print_scaled_value(imu_gyro_z_offset_x1000);
    usb_cdc_write_string(" gyro_z_dps=");
    print_scaled_value(imu_gyro_z_dps_x1000);
    usb_cdc_write_string(" yaw_deg=");
    print_scaled_value(imu_yaw_deg_x1000);
    usb_cdc_write_string("\r\n");
}

static void print_imu_stream_line(void)
{
    char text_buf[120];

    snprintf(text_buf, sizeof(text_buf), "imu stream: raw_z=%d dps=", imu660rb_gyro_z);
    usb_cdc_write_string(text_buf);
    print_scaled_value(imu_gyro_z_dps_x1000);
    usb_cdc_write_string(" yaw=");
    print_scaled_value(imu_yaw_deg_x1000);
    snprintf(text_buf, sizeof(text_buf), " cal=%d sign=%d\r\n", imu_calibrated, imu_yaw_sign);
    usb_cdc_write_string(text_buf);
}

static void print_turn_status(void)
{
    int32 error_x1000;
    char text_buf[160];

    error_x1000 = turn_target_yaw_x1000 - imu_yaw_deg_x1000;
    snprintf(text_buf, sizeof(text_buf),
            "turn: active=%d stable=%d wz=%d kp=",
            turn_active,
            turn_stable_ticks,
            turn_last_wz_deg_s);
    usb_cdc_write_string(text_buf);
    print_scaled_value(turn_kp_x1000);
    snprintf(text_buf, sizeof(text_buf), " max=%d min=%d tol=",
            turn_max_wz_deg_s,
            turn_min_wz_deg_s);
    usb_cdc_write_string(text_buf);
    print_scaled_value(turn_stop_error_x1000);
    usb_cdc_write_string(" target=");
    print_scaled_value(turn_target_yaw_x1000);
    usb_cdc_write_string(" yaw=");
    print_scaled_value(imu_yaw_deg_x1000);
    usb_cdc_write_string(" err=");
    print_scaled_value(error_x1000);
    usb_cdc_write_string("\r\n");

    snprintf(text_buf, sizeof(text_buf),
            "turn comp: left(vx=%d vy=%d) right(vx=%d vy=%d) mm/s\r\n",
            turn_left_comp_vx_mm_s,
            turn_left_comp_vy_mm_s,
            turn_right_comp_vx_mm_s,
            turn_right_comp_vy_mm_s);
    usb_cdc_write_string(text_buf);
}

static void print_wheel_settings(wheel_index_enum wheel)
{
    char text_buf[160];
    wheel_pi_struct *pi;

    pi = &wheel_pi[wheel];

    snprintf(text_buf, sizeof(text_buf),
            "settings: wheel=%s target=%d count/%dms enabled=%d max_duty=%d%% deadband=%d\r\n",
            wheel_table[wheel].name,
            pi->target_speed,
            SAMPLE_PERIOD_MS,
            pi->enabled,
            DUTY_LIMIT_PERCENT,
            ENCODER_DEADBAND_COUNT);
    usb_cdc_write_string(text_buf);

    usb_cdc_write_string("settings: kp=");
    print_scaled_value(pi->kp_x1000);
    usb_cdc_write_string(" ki=");
    print_scaled_value(pi->ki_x1000);
    usb_cdc_write_string(" ffbase+=");
    print_scaled_value(pi->ff_base_pos_x1000);
    usb_cdc_write_string(" ffbase-=");
    print_scaled_value(pi->ff_base_neg_x1000);
    usb_cdc_write_string(" ffslope=");
    print_scaled_value(pi->ff_slope_x1000);
    usb_cdc_write_string(" boost+=");
    print_scaled_value(pi->start_boost_pos_x1000);
    usb_cdc_write_string(" boost-=");
    print_scaled_value(pi->start_boost_neg_x1000);
    snprintf(text_buf, sizeof(text_buf), " ff=%d integral=%ld duty=", pi->ff_enabled, (long)pi->integral);
    usb_cdc_write_string(text_buf);
    print_scaled_value(pi->duty_x1000);
    usb_cdc_write_string("%\r\n");
}

static void print_chassis_motion_status(void)
{
    char text_buf[200];

    if(CHASSIS_MODE_VEL == chassis_mode)
    {
        snprintf(text_buf, sizeof(text_buf),
                "chassis mode: vel vx(right)=%d mm/s vy(forward)=%d mm/s wz(CCW)=%d deg/s\r\n",
                chassis_velocity_vx_mm_s,
                chassis_velocity_vy_mm_s,
                chassis_velocity_wz_deg_s);
        usb_cdc_write_string(text_buf);
    }
    else
    {
        usb_cdc_write_string("chassis mode: manual wheel targets\r\n");
    }

    snprintf(text_buf, sizeof(text_buf),
            "chassis targets: LB=%d RB=%d RF=%d LF=%d count/%dms\r\n",
            wheel_pi[WHEEL_LB].target_speed,
            wheel_pi[WHEEL_RB].target_speed,
            wheel_pi[WHEEL_RF].target_speed,
            wheel_pi[WHEEL_LF].target_speed,
            SAMPLE_PERIOD_MS);
    usb_cdc_write_string(text_buf);
}

static void print_settings(void)
{
    print_wheel_settings(active_wheel);
}

static void print_all_settings(void)
{
    uint8 i;

    usb_cdc_write_string("settings: active wheel=");
    usb_cdc_write_string(wheel_table[active_wheel].name);
    usb_cdc_write_string("\r\n");
    print_chassis_motion_status();
    print_imu_status();
    print_turn_status();

    for(i = 0; i < WHEEL_COUNT; i ++)
    {
        print_wheel_settings((wheel_index_enum)i);
    }
}

static void print_help(void)
{
    usb_cdc_write_string("\r\n========================================\r\n");
    usb_cdc_write_string("Wheel speed PI and four-wheel chassis test through USB CDC\r\n");
    usb_cdc_write_string("Hard duty limit: +/-35%, one selected wheel or four wheel targets can be controlled.\r\n");
    usb_cdc_write_string("Single-byte: 1=run forward, q=run backward, 0/s=stop, z=reset all, h/?=help, +/- target step.\r\n");
    usb_cdc_write_string("Line cmd: wheel lb/rb/rf/lf, run/runall, stop, reset, status(all wheels), target lb 200(set only), targets LB/RB/RF/LF 200 200 200 200, vel vx vy wz, t 200, r 200, b 200, kp 0.020, ki 0.002\r\n");
    usb_cdc_write_string("FF cmd: ff 0/1, ffbase 3.500(set both), ffpos 3.500, ffneg 3.500, ffslope 0.016, boost 18.000, boostpos 18.000, boostneg 18.000\r\n");
    usb_cdc_write_string("IMU cmd: imu status, imu cal, imu stream 1/0, imu sign 1/-1, imu init, yaw, yaw reset\r\n");
    usb_cdc_write_string("Turn cmd: turn 90, turn -90, turn 180, turn left/right/back, turn stop/status, turn kp 1.500, turn max 150, turn min 120, turn tol 2.000, turn lvx/lvy/rvx/rvy\r\n");
    usb_cdc_write_string("Feedback unit: wheel speed uses count/100ms; vel uses mm/s, mm/s, deg/s.\r\n");
    usb_cdc_write_string("Keep wheels off the ground while testing.\r\n");
    usb_cdc_write_string("========================================\r\n");
    print_all_settings();
}

static void print_wheel_control_status(wheel_index_enum wheel, int16 measured_speed)
{
    char text_buf[160];
    wheel_pi_struct *pi;
    int32 error;

    pi = &wheel_pi[wheel];
    error = (int32)pi->target_speed - measured_speed;

    snprintf(text_buf, sizeof(text_buf),
            "%s run=%d target=%d speed=%d err=%ld duty=",
            wheel_table[wheel].name,
            pi->enabled,
            pi->target_speed,
            measured_speed,
            (long)error);
    usb_cdc_write_string(text_buf);
    print_scaled_value(pi->duty_x1000);
    usb_cdc_write_string("% kp=");
    print_scaled_value(pi->kp_x1000);
    usb_cdc_write_string(" ki=");
    print_scaled_value(pi->ki_x1000);
    usb_cdc_write_string(" ff=");
    print_scaled_value(wheel_feedforward_x1000(pi));
    snprintf(text_buf, sizeof(text_buf), " integral=%ld max=%d%%\r\n",
            (long)pi->integral,
            DUTY_LIMIT_PERCENT);
    usb_cdc_write_string(text_buf);
}

static void chassis_stop(void)
{
    uint8 i;

    for(i = 0; i < WHEEL_COUNT; i ++)
    {
        wheel_pi[i].enabled = 0;
    }
    wheel_pi_reset_all();
    motor_stop_all();
    chassis_motion_clear();
}

static void turn_control_start_relative(int16 angle_deg)
{
    char text_buf[160];

    if(!imu_ready)
    {
        usb_cdc_write_string("Turn rejected: IMU not ready. Check IMU wiring or send 'imu init'.\r\n");
        return;
    }
    if(!imu_calibrated)
    {
        usb_cdc_write_string("Turn rejected: IMU not calibrated. Keep car still and send 'imu cal' first.\r\n");
        return;
    }

    angle_deg = clamp_i16(angle_deg, -TURN_ANGLE_LIMIT_DEG, TURN_ANGLE_LIMIT_DEG);
    if(0 == angle_deg)
    {
        usb_cdc_write_string("Turn angle is 0 deg; nothing to do.\r\n");
        return;
    }

    chassis_stop();
    encoder_clear_all();
    wheel_pi_reset_all();

    turn_target_yaw_x1000 = imu_yaw_deg_x1000 + (int32)angle_deg * 1000;
    turn_active = 1;
    turn_stable_ticks = 0;
    turn_status_counter = 0;
    turn_last_wz_deg_s = 0;

    snprintf(text_buf, sizeof(text_buf), "Turn start: relative=%d deg current_yaw=", angle_deg);
    usb_cdc_write_string(text_buf);
    print_scaled_value(imu_yaw_deg_x1000);
    usb_cdc_write_string(" target_yaw=");
    print_scaled_value(turn_target_yaw_x1000);
    usb_cdc_write_string("\r\n");
}

static void turn_control_update(void)
{
    int32 error_x1000;
    int32 abs_error_x1000;
    int32 wz_candidate;
    int16 vx_command;
    int16 vy_command;
    int16 wz_command;

    if(!turn_active)
    {
        return;
    }

    if(!imu_ready || !imu_calibrated)
    {
        chassis_stop();
        usb_cdc_write_string("Turn stopped: IMU became unavailable or uncalibrated.\r\n");
        return;
    }

    error_x1000 = turn_target_yaw_x1000 - imu_yaw_deg_x1000;
    abs_error_x1000 = abs_i32(error_x1000);

    if(abs_error_x1000 <= turn_stop_error_x1000)
    {
        turn_last_wz_deg_s = 0;
        chassis_apply_velocity_targets(0, 0, 0);
        turn_stable_ticks ++;

        if(turn_stable_ticks >= TURN_STABLE_TICKS)
        {
            chassis_stop();
            usb_cdc_write_string("Turn done. ");
            print_turn_status();
            return;
        }
    }
    else
    {
        turn_stable_ticks = 0;
        wz_candidate = round_i64_div((int64)error_x1000 * turn_kp_x1000, 1000000);

        if(wz_candidate > turn_max_wz_deg_s)
        {
            wz_candidate = turn_max_wz_deg_s;
        }
        else if(wz_candidate < -turn_max_wz_deg_s)
        {
            wz_candidate = -turn_max_wz_deg_s;
        }

        if((wz_candidate > 0) && (wz_candidate < turn_min_wz_deg_s))
        {
            wz_candidate = turn_min_wz_deg_s;
        }
        else if((wz_candidate < 0) && (wz_candidate > -turn_min_wz_deg_s))
        {
            wz_candidate = -turn_min_wz_deg_s;
        }

        wz_command = clamp_i16(wz_candidate, -turn_max_wz_deg_s, turn_max_wz_deg_s);
        vx_command = 0;
        vy_command = 0;
        if(wz_command > 0)
        {
            vx_command = turn_left_comp_vx_mm_s;
            vy_command = turn_left_comp_vy_mm_s;
        }
        else if(wz_command < 0)
        {
            vx_command = turn_right_comp_vx_mm_s;
            vy_command = turn_right_comp_vy_mm_s;
        }
        turn_last_wz_deg_s = wz_command;
        chassis_apply_velocity_targets(vx_command, vy_command, wz_command);
    }

    turn_status_counter ++;
    if(turn_status_counter >= TURN_STATUS_PERIOD_TICKS)
    {
        turn_status_counter = 0;
        print_turn_status();
    }
}

static void process_turn_command(const char *arg)
{
    int16 value;
    int32 parameter;
    char text_buf[120];

    arg = skip_spaces(arg);

    if(('\0' == *arg) || command_name_match(arg, "status"))
    {
        print_turn_status();
    }
    else if(command_name_match(arg, "stop") || command_name_match(arg, "cancel"))
    {
        chassis_stop();
        usb_cdc_write_string("Turn stopped by command.\r\n");
        print_turn_status();
    }
    else if(command_name_match(arg, "left") || command_name_match(arg, "l"))
    {
        turn_control_start_relative(90);
    }
    else if(command_name_match(arg, "right") || command_name_match(arg, "r"))
    {
        turn_control_start_relative(-90);
    }
    else if(command_name_match(arg, "back") || command_name_match(arg, "u") || command_name_match(arg, "uturn"))
    {
        turn_control_start_relative(180);
    }
    else if(command_name_match(arg, "kp"))
    {
        if(0 == parse_scaled_1000(command_argument(arg), &parameter))
        {
            turn_kp_x1000 = clamp_i32(parameter, 500, 5000);
            usb_cdc_write_string("Turn Kp set: ");
            print_scaled_value(turn_kp_x1000);
            usb_cdc_write_string("\r\n");
        }
        else
        {
            usb_cdc_write_string("Bad turn kp command. Example: turn kp 2.000\r\n");
        }
    }
    else if(command_name_match(arg, "max"))
    {
        if(0 == parse_int16_value(command_argument(arg), &value))
        {
            turn_max_wz_deg_s = clamp_i16(value, 30, 360);
            if(turn_min_wz_deg_s > turn_max_wz_deg_s)
            {
                turn_min_wz_deg_s = turn_max_wz_deg_s;
            }
            snprintf(text_buf, sizeof(text_buf), "Turn max wz set: %d deg/s\r\n", turn_max_wz_deg_s);
            usb_cdc_write_string(text_buf);
        }
        else
        {
            usb_cdc_write_string("Bad turn max command. Example: turn max 160\r\n");
        }
    }
    else if(command_name_match(arg, "min"))
    {
        if(0 == parse_int16_value(command_argument(arg), &value))
        {
            turn_min_wz_deg_s = clamp_i16(value, 0, turn_max_wz_deg_s);
            snprintf(text_buf, sizeof(text_buf), "Turn min wz set: %d deg/s\r\n", turn_min_wz_deg_s);
            usb_cdc_write_string(text_buf);
        }
        else
        {
            usb_cdc_write_string("Bad turn min command. Example: turn min 25\r\n");
        }
    }
    else if(command_name_match(arg, "tol") || command_name_match(arg, "tolerance"))
    {
        if(0 == parse_scaled_1000(command_argument(arg), &parameter))
        {
            turn_stop_error_x1000 = clamp_i32(parameter, 300, 5000);
            usb_cdc_write_string("Turn stop tolerance set: ");
            print_scaled_value(turn_stop_error_x1000);
            usb_cdc_write_string(" deg\r\n");
        }
        else
        {
            usb_cdc_write_string("Bad turn tol command. Example: turn tol 1.000\r\n");
        }
    }
    else if(command_name_match(arg, "lvx"))
    {
        if(0 == parse_int16_value(command_argument(arg), &value))
        {
            turn_left_comp_vx_mm_s = clamp_i16(value, -TURN_COMP_LIMIT_MM_S, TURN_COMP_LIMIT_MM_S);
            snprintf(text_buf, sizeof(text_buf), "Turn left vx compensation set: %d mm/s\r\n", turn_left_comp_vx_mm_s);
            usb_cdc_write_string(text_buf);
        }
        else
        {
            usb_cdc_write_string("Bad turn left vx command. Example: turn lvx 10\r\n");
        }
    }
    else if(command_name_match(arg, "lvy"))
    {
        if(0 == parse_int16_value(command_argument(arg), &value))
        {
            turn_left_comp_vy_mm_s = clamp_i16(value, -TURN_COMP_LIMIT_MM_S, TURN_COMP_LIMIT_MM_S);
            snprintf(text_buf, sizeof(text_buf), "Turn left vy compensation set: %d mm/s\r\n", turn_left_comp_vy_mm_s);
            usb_cdc_write_string(text_buf);
        }
        else
        {
            usb_cdc_write_string("Bad turn left vy command. Example: turn lvy -10\r\n");
        }
    }
    else if(command_name_match(arg, "rvx"))
    {
        if(0 == parse_int16_value(command_argument(arg), &value))
        {
            turn_right_comp_vx_mm_s = clamp_i16(value, -TURN_COMP_LIMIT_MM_S, TURN_COMP_LIMIT_MM_S);
            snprintf(text_buf, sizeof(text_buf), "Turn right vx compensation set: %d mm/s\r\n", turn_right_comp_vx_mm_s);
            usb_cdc_write_string(text_buf);
        }
        else
        {
            usb_cdc_write_string("Bad turn right vx command. Example: turn rvx 10\r\n");
        }
    }
    else if(command_name_match(arg, "rvy"))
    {
        if(0 == parse_int16_value(command_argument(arg), &value))
        {
            turn_right_comp_vy_mm_s = clamp_i16(value, -TURN_COMP_LIMIT_MM_S, TURN_COMP_LIMIT_MM_S);
            snprintf(text_buf, sizeof(text_buf), "Turn right vy compensation set: %d mm/s\r\n", turn_right_comp_vy_mm_s);
            usb_cdc_write_string(text_buf);
        }
        else
        {
            usb_cdc_write_string("Bad turn right vy command. Example: turn rvy -10\r\n");
        }
    }
    else if(command_name_match(arg, "compreset"))
    {
        turn_left_comp_vx_mm_s = TURN_LEFT_COMP_VX_DEFAULT_MM_S;
        turn_left_comp_vy_mm_s = TURN_LEFT_COMP_VY_DEFAULT_MM_S;
        turn_right_comp_vx_mm_s = TURN_RIGHT_COMP_VX_DEFAULT_MM_S;
        turn_right_comp_vy_mm_s = TURN_RIGHT_COMP_VY_DEFAULT_MM_S;
        usb_cdc_write_string("Turn translation compensation reset to calibrated defaults.\r\n");
        print_turn_status();
    }
    else if(0 == parse_int16_value(arg, &value))
    {
        turn_control_start_relative(value);
    }
    else
    {
        usb_cdc_write_string("Bad turn command. Use: turn 90, turn -90, turn 180, turn left/right/back, turn stop/status, turn lvx/lvy/rvx/rvy 0\r\n");
    }
}

static void active_start_with_target(int16 target_speed)
{
    chassis_stop();
    wheel_set_target_raw(active_wheel, target_speed);
    wheel_pi_reset(active_wheel);
    encoder_clear_all();
    wheel_pi[active_wheel].enabled = 1;
}

static void chassis_start_with_targets(int16 lb_target, int16 rb_target, int16 rf_target, int16 lf_target)
{
    uint8 i;

    chassis_stop();
    wheel_set_target_raw(WHEEL_LB, lb_target);
    wheel_set_target_raw(WHEEL_RB, rb_target);
    wheel_set_target_raw(WHEEL_RF, rf_target);
    wheel_set_target_raw(WHEEL_LF, lf_target);
    encoder_clear_all();

    for(i = 0; i < WHEEL_COUNT; i ++)
    {
        wheel_pi[(wheel_index_enum)i].enabled = 1;
    }
}

static void chassis_start_all_current_targets(void)
{
    uint8 i;

    chassis_stop();
    encoder_clear_all();

    for(i = 0; i < WHEEL_COUNT; i ++)
    {
        wheel_pi[(wheel_index_enum)i].enabled = 1;
    }
}

static uint8 chassis_start_with_velocity(int16 vx_mm_s, int16 vy_mm_s, int16 wz_deg_s)
{
    int16 targets[WHEEL_COUNT];
    uint8 limited;

    limited = chassis_velocity_to_targets(vx_mm_s, vy_mm_s, wz_deg_s, targets);
    chassis_start_with_targets(targets[WHEEL_LB], targets[WHEEL_RB], targets[WHEEL_RF], targets[WHEEL_LF]);
    chassis_motion_set_velocity(vx_mm_s, vy_mm_s, wz_deg_s);

    return limited;
}

static uint8 chassis_apply_velocity_targets(int16 vx_mm_s, int16 vy_mm_s, int16 wz_deg_s)
{
    int16 targets[WHEEL_COUNT];
    uint8 limited;
    uint8 i;

    limited = chassis_velocity_to_targets(vx_mm_s, vy_mm_s, wz_deg_s, targets);
    wheel_set_target_keep_motion(WHEEL_LB, targets[WHEEL_LB]);
    wheel_set_target_keep_motion(WHEEL_RB, targets[WHEEL_RB]);
    wheel_set_target_keep_motion(WHEEL_RF, targets[WHEEL_RF]);
    wheel_set_target_keep_motion(WHEEL_LF, targets[WHEEL_LF]);

    for(i = 0; i < WHEEL_COUNT; i ++)
    {
        wheel_pi[(wheel_index_enum)i].enabled = 1;
    }

    chassis_motion_set_velocity(vx_mm_s, vy_mm_s, wz_deg_s);
    return limited;
}

static void process_imu_command(const char *arg)
{
    const char *value_arg;
    int16 value;
    char text_buf[100];

    arg = skip_spaces(arg);

    if('\0' == *arg)
    {
        print_imu_status();
    }
    else if(command_name_match(arg, "status"))
    {
        print_imu_status();
    }
    else if(command_name_match(arg, "init"))
    {
        imu_init_device();
        print_imu_status();
    }
    else if(command_name_match(arg, "cal") || command_name_match(arg, "calibrate"))
    {
        chassis_stop();
        usb_cdc_write_string("All wheel PI stopped before IMU calibration.\r\n");
        imu_calibrate_gyro_z();
        print_imu_status();
    }
    else if(command_name_match(arg, "reset"))
    {
        chassis_stop();
        imu_yaw_reset();
        usb_cdc_write_string("All wheel PI stopped. IMU yaw reset to 0 deg.\r\n");
        print_imu_status();
    }
    else if(command_name_match(arg, "stream"))
    {
        value_arg = skip_spaces(command_argument(arg));
        if('\0' == *value_arg)
        {
            imu_stream_enabled = !imu_stream_enabled;
        }
        else if(0 == parse_int16_value(value_arg, &value))
        {
            imu_stream_enabled = (0 == value) ? 0 : 1;
        }
        else
        {
            usb_cdc_write_string("Bad IMU stream command. Example: imu stream 1\r\n");
            return;
        }
        imu_stream_counter = 0;
        snprintf(text_buf, sizeof(text_buf), "IMU stream enabled: %d\r\n", imu_stream_enabled);
        usb_cdc_write_string(text_buf);
    }
    else if(command_name_match(arg, "sign"))
    {
        if(0 == parse_int16_value(command_argument(arg), &value))
        {
            chassis_stop();
            imu_yaw_sign = (value < 0) ? -1 : 1;
            imu_yaw_reset();
            snprintf(text_buf, sizeof(text_buf), "All wheel PI stopped. IMU yaw sign set: %d, yaw reset to 0 deg.\r\n", imu_yaw_sign);
            usb_cdc_write_string(text_buf);
        }
        else
        {
            usb_cdc_write_string("Bad IMU sign command. Example: imu sign -1\r\n");
        }
    }
    else
    {
        usb_cdc_write_string("Bad IMU command. Use: imu status, imu cal, imu stream 1/0, imu sign 1/-1, imu init\r\n");
    }
}

static void process_yaw_command(const char *arg)
{
    arg = skip_spaces(arg);

    if(('\0' == *arg) || command_name_match(arg, "status"))
    {
        print_imu_status();
    }
    else if(command_name_match(arg, "reset") || command_name_match(arg, "zero"))
    {
        chassis_stop();
        imu_yaw_reset();
        usb_cdc_write_string("All wheel PI stopped. Yaw reset to 0 deg.\r\n");
        print_imu_status();
    }
    else
    {
        usb_cdc_write_string("Bad yaw command. Use: yaw or yaw reset\r\n");
    }
}

static void active_wheel_select(wheel_index_enum wheel)
{
    chassis_stop();
    active_wheel = wheel;
    encoder_clear_all();
}

static void active_target_magnitude_change(int16 delta)
{
    wheel_pi_struct *pi;
    int16 magnitude;
    int16 sign;

    pi = &wheel_pi[active_wheel];
    sign = (pi->target_speed < 0) ? -1 : 1;
    magnitude = abs_i16(pi->target_speed);
    magnitude = clamp_i16((int32)magnitude + delta, 0, TARGET_LIMIT_SPEED);
    if(0 == magnitude)
    {
        wheel_set_target_raw(active_wheel, 0);
    }
    else
    {
        wheel_set_target_raw(active_wheel, magnitude * sign);
    }

    wheel_pi_reset(active_wheel);
}

static void process_short_command(uint8 command)
{
    char text_buf[80];
    wheel_pi_struct *pi;
    int16 magnitude;

    pi = &wheel_pi[active_wheel];

    switch(command)
    {
        case '1':
            magnitude = abs_i16(pi->target_speed);
            if(0 == magnitude)
            {
                magnitude = DEFAULT_START_TARGET_SPEED;
            }
            active_start_with_target(magnitude);
            snprintf(text_buf, sizeof(text_buf), "%s PI start forward.\r\n", wheel_table[active_wheel].name);
            usb_cdc_write_string(text_buf);
            break;

        case 'q':
        case 'Q':
            magnitude = abs_i16(pi->target_speed);
            if(0 == magnitude)
            {
                magnitude = DEFAULT_START_TARGET_SPEED;
            }
            active_start_with_target(-magnitude);
            snprintf(text_buf, sizeof(text_buf), "%s PI start backward.\r\n", wheel_table[active_wheel].name);
            usb_cdc_write_string(text_buf);
            break;

        case '+':
            active_target_magnitude_change(TARGET_STEP_SPEED);
            snprintf(text_buf, sizeof(text_buf), "Target magnitude increased: target=%d\r\n", pi->target_speed);
            usb_cdc_write_string(text_buf);
            break;

        case '-':
            active_target_magnitude_change(-TARGET_STEP_SPEED);
            snprintf(text_buf, sizeof(text_buf), "Target magnitude decreased: target=%d\r\n", pi->target_speed);
            usb_cdc_write_string(text_buf);
            break;

        default:
            break;
    }
}

static void process_line_command(const char *line)
{
    int16 target;
    int16 chassis_targets[WHEEL_COUNT];
    int32 parameter;
    const char *wheel_arg;
    const char *target_arg;
    wheel_pi_struct *pi;
    wheel_index_enum selected_wheel;
    char text_buf[120];

    pi = &wheel_pi[active_wheel];

    if(command_name_match(line, "wheel") || command_name_match(line, "w"))
    {
        if(0 == parse_wheel_index(command_argument(line), &selected_wheel))
        {
            active_wheel_select(selected_wheel);
            snprintf(text_buf, sizeof(text_buf), "Active wheel selected: %s\r\n", wheel_table[active_wheel].name);
            usb_cdc_write_string(text_buf);
            print_settings();
        }
        else
        {
            usb_cdc_write_string("Bad wheel command. Example: wheel lb\r\n");
        }
    }
    else if(command_name_match(line, "run") || command_name_match(line, "start"))
    {
        active_start_with_target(pi->target_speed);
        snprintf(text_buf, sizeof(text_buf), "%s PI start.\r\n", wheel_table[active_wheel].name);
        usb_cdc_write_string(text_buf);
    }
    else if(command_name_match(line, "stop") || command_name_match(line, "0") || command_name_match(line, "s"))
    {
        chassis_stop();
        usb_cdc_write_string("All wheel PI stopped.\r\n");
    }
    else if(command_name_match(line, "reset") || command_name_match(line, "z"))
    {
        encoder_clear_all();
        wheel_pi_reset_all();
        usb_cdc_write_string("All encoders and PI integrals reset.\r\n");
    }
    else if(command_name_match(line, "status"))
    {
        print_all_settings();
    }
    else if(command_name_match(line, "imu"))
    {
        process_imu_command(command_argument(line));
    }
    else if(command_name_match(line, "yaw"))
    {
        process_yaw_command(command_argument(line));
    }
    else if(command_name_match(line, "turn"))
    {
        process_turn_command(command_argument(line));
    }
    else if(command_name_match(line, "target"))
    {
        wheel_arg = command_argument(line);
        if(0 == parse_wheel_index(wheel_arg, &selected_wheel))
        {
            target_arg = command_argument(wheel_arg);
            if(0 == parse_int16_value(target_arg, &target))
            {
                wheel_set_target_raw(selected_wheel, target);
                wheel_pi_reset(selected_wheel);
                snprintf(text_buf, sizeof(text_buf), "Wheel target set only: %s %d count/%dms\r\n",
                         wheel_table[selected_wheel].name,
                         wheel_pi[selected_wheel].target_speed,
                         SAMPLE_PERIOD_MS);
                usb_cdc_write_string(text_buf);
            }
            else
            {
                usb_cdc_write_string("Bad target value. Example: target lb 200\r\n");
            }
        }
        else
        {
            usb_cdc_write_string("Bad target command. Example: target lb 200\r\n");
        }
    }
    else if(command_name_match(line, "runall") || command_name_match(line, "startall") || command_name_match(line, "allrun"))
    {
        chassis_start_all_current_targets();
        usb_cdc_write_string("All wheel PI started with current targets.\r\n");
        print_all_settings();
    }
    else if(command_name_match(line, "targets") || command_name_match(line, "chassis"))
    {
        if(0 == parse_four_int16_values(command_argument(line), chassis_targets))
        {
            chassis_start_with_targets(chassis_targets[WHEEL_LB], chassis_targets[WHEEL_RB],
                                       chassis_targets[WHEEL_RF], chassis_targets[WHEEL_LF]);
            usb_cdc_write_string("Chassis targets set and all wheels started.\r\n");
            print_all_settings();
        }
        else
        {
            usb_cdc_write_string("Bad targets command. Example: targets 200 200 200 200\r\n");
        }
    }
    else if(command_name_match(line, "vel"))
    {
        int16 chassis_velocity[3];
        uint8 limited;

        if(0 == parse_three_int16_values(command_argument(line), chassis_velocity))
        {
            limited = chassis_start_with_velocity(chassis_velocity[0], chassis_velocity[1], chassis_velocity[2]);
            usb_cdc_write_string("Chassis velocity set and all wheels started.\r\n");
            if(limited)
            {
                usb_cdc_write_string("Note: wheel targets were clamped to +/-2000 count/100ms.\r\n");
            }
            print_all_settings();
        }
        else
        {
            usb_cdc_write_string("Bad vel command. Example: vel 0 200 0\r\n");
        }
    }
    else if(command_name_match(line, "t"))
    {
        if(0 == parse_int16_value(command_argument(line), &target))
        {
            wheel_set_target_raw(active_wheel, target);
            wheel_pi_reset(active_wheel);
            snprintf(text_buf, sizeof(text_buf), "Target set: %d count/%dms\r\n", pi->target_speed, SAMPLE_PERIOD_MS);
            usb_cdc_write_string(text_buf);
        }
        else
        {
            usb_cdc_write_string("Bad target command. Example: t 200\r\n");
        }
    }
    else if(command_name_match(line, "r"))
    {
        if(0 == parse_int16_value(command_argument(line), &target))
        {
            active_start_with_target(abs_i16(target));
            snprintf(text_buf, sizeof(text_buf), "%s PI start forward with new target.\r\n", wheel_table[active_wheel].name);
            usb_cdc_write_string(text_buf);
        }
        else
        {
            usb_cdc_write_string("Bad run command. Example: r 200\r\n");
        }
    }
    else if(command_name_match(line, "b"))
    {
        if(0 == parse_int16_value(command_argument(line), &target))
        {
            active_start_with_target(-abs_i16(target));
            snprintf(text_buf, sizeof(text_buf), "%s PI start backward with new target.\r\n", wheel_table[active_wheel].name);
            usb_cdc_write_string(text_buf);
        }
        else
        {
            usb_cdc_write_string("Bad backward command. Example: b 200\r\n");
        }
    }
    else if(command_name_match(line, "kp"))
    {
        if(0 == parse_scaled_1000(command_argument(line), &parameter))
        {
            pi->kp_x1000 = clamp_i32(parameter, 0, 1000);
            wheel_pi_reset(active_wheel);
            usb_cdc_write_string("Kp set: ");
            print_scaled_value(pi->kp_x1000);
            usb_cdc_write_string("\r\n");
        }
        else
        {
            usb_cdc_write_string("Bad Kp command. Example: kp 0.020\r\n");
        }
    }
    else if(command_name_match(line, "ki"))
    {
        if(0 == parse_scaled_1000(command_argument(line), &parameter))
        {
            pi->ki_x1000 = clamp_i32(parameter, 0, 1000);
            wheel_pi_reset(active_wheel);
            usb_cdc_write_string("Ki set: ");
            print_scaled_value(pi->ki_x1000);
            usb_cdc_write_string("\r\n");
        }
        else
        {
            usb_cdc_write_string("Bad Ki command. Example: ki 0.002\r\n");
        }
    }
    else if(command_name_match(line, "ffbase"))
    {
        if(0 == parse_scaled_1000(command_argument(line), &parameter))
        {
            parameter = clamp_i32(parameter, 0, DUTY_LIMIT_X1000);
            pi->ff_base_pos_x1000 = parameter;
            pi->ff_base_neg_x1000 = parameter;
            wheel_pi_reset(active_wheel);
            usb_cdc_write_string("FF base set for both directions: ");
            print_scaled_value(parameter);
            usb_cdc_write_string("%\r\n");
        }
        else
        {
            usb_cdc_write_string("Bad FF base command. Example: ffbase 3.500\r\n");
        }
    }
    else if(command_name_match(line, "ffpos"))
    {
        if(0 == parse_scaled_1000(command_argument(line), &parameter))
        {
            pi->ff_base_pos_x1000 = clamp_i32(parameter, 0, DUTY_LIMIT_X1000);
            wheel_pi_reset(active_wheel);
            usb_cdc_write_string("FF positive base set: ");
            print_scaled_value(pi->ff_base_pos_x1000);
            usb_cdc_write_string("%\r\n");
        }
        else
        {
            usb_cdc_write_string("Bad FF positive base command. Example: ffpos 3.500\r\n");
        }
    }
    else if(command_name_match(line, "ffneg"))
    {
        if(0 == parse_scaled_1000(command_argument(line), &parameter))
        {
            pi->ff_base_neg_x1000 = clamp_i32(parameter, 0, DUTY_LIMIT_X1000);
            wheel_pi_reset(active_wheel);
            usb_cdc_write_string("FF negative base set: ");
            print_scaled_value(pi->ff_base_neg_x1000);
            usb_cdc_write_string("%\r\n");
        }
        else
        {
            usb_cdc_write_string("Bad FF negative base command. Example: ffneg 3.500\r\n");
        }
    }
    else if(command_name_match(line, "ffslope"))
    {
        if(0 == parse_scaled_1000(command_argument(line), &parameter))
        {
            pi->ff_slope_x1000 = clamp_i32(parameter, 0, FF_SLOPE_LIMIT_X1000);
            wheel_pi_reset(active_wheel);
            usb_cdc_write_string("FF slope set: ");
            print_scaled_value(pi->ff_slope_x1000);
            usb_cdc_write_string("\r\n");
        }
        else
        {
            usb_cdc_write_string("Bad FF slope command. Example: ffslope 0.016\r\n");
        }
    }
    else if(command_name_match(line, "boost"))
    {
        if(0 == parse_scaled_1000(command_argument(line), &parameter))
        {
            parameter = clamp_i32(parameter, 0, DUTY_LIMIT_X1000);
            pi->start_boost_pos_x1000 = parameter;
            pi->start_boost_neg_x1000 = parameter;
            wheel_pi_reset(active_wheel);
            usb_cdc_write_string("Start boost set for both directions: ");
            print_scaled_value(parameter);
            usb_cdc_write_string("%\r\n");
        }
        else
        {
            usb_cdc_write_string("Bad start boost command. Example: boost 18.000\r\n");
        }
    }
    else if(command_name_match(line, "boostpos"))
    {
        if(0 == parse_scaled_1000(command_argument(line), &parameter))
        {
            pi->start_boost_pos_x1000 = clamp_i32(parameter, 0, DUTY_LIMIT_X1000);
            wheel_pi_reset(active_wheel);
            usb_cdc_write_string("Start boost positive set: ");
            print_scaled_value(pi->start_boost_pos_x1000);
            usb_cdc_write_string("%\r\n");
        }
        else
        {
            usb_cdc_write_string("Bad positive start boost command. Example: boostpos 18.000\r\n");
        }
    }
    else if(command_name_match(line, "boostneg"))
    {
        if(0 == parse_scaled_1000(command_argument(line), &parameter))
        {
            pi->start_boost_neg_x1000 = clamp_i32(parameter, 0, DUTY_LIMIT_X1000);
            wheel_pi_reset(active_wheel);
            usb_cdc_write_string("Start boost negative set: ");
            print_scaled_value(pi->start_boost_neg_x1000);
            usb_cdc_write_string("%\r\n");
        }
        else
        {
            usb_cdc_write_string("Bad negative start boost command. Example: boostneg 18.000\r\n");
        }
    }
    else if(command_name_match(line, "ff"))
    {
        if(0 == parse_int16_value(command_argument(line), &target))
        {
            pi->ff_enabled = (0 == target) ? 0 : 1;
            wheel_pi_reset(active_wheel);
            snprintf(text_buf, sizeof(text_buf), "FF enabled: %d\r\n", pi->ff_enabled);
            usb_cdc_write_string(text_buf);
        }
        else
        {
            usb_cdc_write_string("Bad FF command. Example: ff 1\r\n");
        }
    }
    else if(command_name_match(line, "h") || command_name_match(line, "help") || command_name_match(line, "?"))
    {
        print_help();
    }
    else if(command_name_match(line, "1"))
    {
        process_short_command('1');
    }
    else if(command_name_match(line, "q"))
    {
        process_short_command('q');
    }
    else if(command_name_match(line, "+"))
    {
        process_short_command('+');
    }
    else if(command_name_match(line, "-"))
    {
        process_short_command('-');
    }
    else
    {
        usb_cdc_write_string("Unknown command. Send h for help.\r\n");
    }
}

int main(void)
{
    int16 measured_speed;
    int32 duty_output;
    wheel_pi_struct *pi;
    wheel_index_enum wheel;
    uint8 short_command;
    char line_local[RX_LINE_MAX];
    uint8 i;

    clock_init(SYSTEM_CLOCK_600M);
    debug_init();
    usb_cdc_init();

    system_delay_ms(800);

    motor_init_all();
    motor_stop_all();
    encoder_init_all();
    interrupt_global_enable(0);
    imu_init_device();

    print_help();

    while(1)
    {
        if(chassis_stop_request)
        {
            chassis_stop_request = 0;
            chassis_stop();
            usb_cdc_write_string("All wheel PI stopped.\r\n");
        }

        if(chassis_reset_request)
        {
            chassis_reset_request = 0;
            encoder_clear_all();
            wheel_pi_reset_all();
            usb_cdc_write_string("All encoders and PI integrals reset.\r\n");
        }

        if(chassis_help_request)
        {
            chassis_help_request = 0;
            print_help();
        }

        if(chassis_short_command)
        {
            short_command = chassis_short_command;
            chassis_short_command = 0;
            process_short_command(short_command);
        }

        if(chassis_line_ready)
        {
            for(i = 0; i < RX_LINE_MAX; i ++)
            {
                line_local[i] = chassis_line_buffer[i];
                if('\0' == line_local[i])
                {
                    break;
                }
            }
            line_local[RX_LINE_MAX - 1] = '\0';
            chassis_line_ready = 0;
            process_line_command(line_local);
        }

        imu_update();
        turn_control_update();

        for(i = 0; i < WHEEL_COUNT; i ++)
        {
            wheel = (wheel_index_enum)i;
            measured_speed = encoder_read_forward_count(wheel);
            pi = &wheel_pi[wheel];

            if(pi->enabled)
            {
                duty_output = wheel_pi_update(wheel, measured_speed);
                motor_set_forward_duty_x1000(wheel, duty_output);
                print_wheel_control_status(wheel, measured_speed);
            }
            else
            {
                pi->duty_x1000 = 0;
                motor_set_forward_duty_x1000(wheel, 0);
            }
        }

        if(imu_stream_enabled && imu_ready)
        {
            imu_stream_counter ++;
            if(imu_stream_counter >= IMU_STREAM_PERIOD_TICKS)
            {
                imu_stream_counter = 0;
                print_imu_stream_line();
            }
        }
        system_delay_ms(SAMPLE_PERIOD_MS);
    }
}
