/**
 * Lys is a simple protocol that uses Segger's Real Time Transfer functionality
 * to provide synchronization and serialized data transfer between a PC and an
 * embedded device.
 *
 * Simple Lys messages are in the form:
 *    [LEN (1)][OP (1)]
 *    where the LEN is the message length including the LEN byte itself.
 *
 * LYS_OP_PARAM and LYS_OP_LOG messages are in the form:
 *     [LEN (1)][OP (1)][lys_param_type_t (1)][data (p)]
 *     where p is the length of the specified lys_param_type_t. NOTE: Strings of
 *     length zero are not allowed.
 *
 * LYS_PARAM_TYPE_ARRAY messages are in the form:
 *     [LEN (1)][OP (1)][LYS_PARAM_TYPE_ARRAY (1)][lys_param_type_t (1)][data (n * p)]
 *     where n is the length of the array and p is the length of the specified
 *     lys_param_type_t. NOTE: Nested arrays, arrays of strings, and arrays of length
 *     zero are not allowed.
 */
#ifndef LYS_H__
#define LYS_H__

#ifdef __cplusplus
extern "C" {
#endif


#define LYS_MAX_STR_LEN   (64UL)
#define LYS_MAX_ARRAY_LEN (64UL)
#define LYS_MAX_MSG_LEN   (64UL)
#if LYS_MAX_MSG_LEN > 255
    #error This library assumes that Lys message lengths will fit in a uint8_t.
#endif


// NOTE: These error codes are used by this C library and aren't part of the
//       Lys protocol itself.
typedef enum
{
    LYS_ERROR_SUCCESS = 0,
    LYS_ERROR_INVALID_STATE,
    LYS_ERROR_INVALID_PARAM,
    LYS_ERROR_COUNT
} lys_error_t;


// NOTE: These states are used by this C library and aren't part of the Lys
//       protocol itself.
typedef enum
{
    LYS_STATE_UNKNOWN = 0,    // Start in UNKNOWN. Then send INIT.
    LYS_STATE_WAIT_FOR_START, // Read params until START is received.
    LYS_STATE_RUNNING,        // Run until RESULT is sent.
    LYS_STATE_RESULT,         // Send result params and then send FINISHED.
    LYS_STATE_FINISHED,       // Loop forever or log?
    LYS_STATE_COUNT
} lys_state_t;


typedef enum
{
    LYS_OP_UNKNOWN = 0,
    LYS_OP_INIT,
    LYS_OP_START,
    LYS_OP_RESULT,
    LYS_OP_FINISHED,
    LYS_OP_PARAM,
    LYS_OP_ACK,
    LYS_OP_LOG,
    LYS_OP_COUNT
} lys_op_t;


typedef enum
{
    LYS_PARAM_TYPE_UINT32 = 0,
    LYS_PARAM_TYPE_INT32,
    LYS_PARAM_TYPE_UINT8,
    LYS_PARAM_TYPE_INT8,
    LYS_PARAM_TYPE_BOOL,
    LYS_PARAM_TYPE_STRING,
    LYS_PARAM_TYPE_ARRAY,
    LYS_PARAM_TYPE_COUNT
} lys_param_type_t;


// NOTE: Strings are not required to be null-terminated.
typedef struct
{
    uint32_t len;
    uint8_t  *p_data;
} lys_str_t;


// NOTE: Strings and nested arrays are not allowed.
typedef struct
{
    lys_param_type_t param_type;
    uint32_t         item_count;
    union
    {
        uint32_t *p_uint32;
        int32_t  *p_int32;
        uint8_t  *p_uint8;
        int8_t   *p_int8;
        bool     *p_bool;
    } data;
} lys_array_t;


typedef struct
{
    lys_param_type_t param_type;
    union
    {
        uint32_t    *p_uint32;
        int32_t     *p_int32;
        uint8_t     *p_uint8;
        int8_t      *p_int8;
        bool        *p_bool;
        lys_str_t   *p_str;
        lys_array_t *p_array;
    } data;
} lys_param_t;


#define LYS_PARAM_VARIABLE_SIZE    (0UL)


// Must be called first. Can be called multiple times.
void lys_init(void);

// Returns the current state.
lys_state_t lys_state_get(void);

// Returns true if an error has occurred that caused the library to enter
// the LYS_STATE_UNKNOWN state.
bool lys_has_error(void);

// Blocks until the next param is received. If there are no more params to
// receive then p_param_set will be set to false. If the current state is not
// LYS_STATE_WAIT_FOR_START then LYS_ERROR_INVALID_STATE will be returned.
lys_error_t lys_param_wait(lys_param_t **p_param, bool *p_param_set);

// Convenience function for receiving an array of params. Params are read from
// the list in order and the param data is copied to the data pointers in the
// list. Expects the final param to be followed by a LYS_OP_START op.
lys_error_t lys_params_receive(const lys_param_t *p_params, uint32_t param_count);

// Sends the given param data to the PC. Returns LYS_ERROR_INVALID_STATE if
// the current state is not LYS_STATE_RESULT.
lys_error_t lys_param_send(const lys_param_t *p_param);

// Convenience function for sending an array of params. Params are sent from
// the list in order. Sends the LYS_OP_FINISHED op when it's complete.
lys_error_t lys_results_send(const lys_param_t *params, uint32_t param_count);

// Notifies the PC that there are no more result params to send.
lys_error_t lys_finish(void);

// Notifies the PC that there was an error via the LYS_STATE_UNKNOWN op.
lys_error_t lys_error_send(void);

// Sends the specified string for logging purposes. Returns
// LYS_ERROR_INVALID_STATE during the LYS_STATE_WAIT_FOR_START and
// LYS_STATE_RESULT states. NOTE: If the PC has closed its RTT session then
// this function will block indefinitely.
lys_error_t lys_log_send(const lys_str_t *p_str);

// Returns the param's expected len or LYS_PARAM_VARIABLE_SIZE if it's an
// array or str.
lys_error_t lys_param_len_lookup(lys_param_type_t param_type, uint32_t *p_len);

#ifdef __cplusplus
}
#endif

#endif