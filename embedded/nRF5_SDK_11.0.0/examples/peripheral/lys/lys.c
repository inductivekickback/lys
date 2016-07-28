#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#include "SEGGER_RTT.h"
#include "lys.h"


#define LYS_RTT_CHANNEL            (0UL)

#define LYS_LEN_INDEX              (0UL)
#define LYS_OP_INDEX               (1UL)
#define LYS_PARAM_TYPE_INDEX       (2UL)
#define LYS_DATA_INDEX             (3UL)
#define LYS_ARRAY_PARAM_TYPE_INDEX (3UL)
#define LYS_ARRAY_DATA_INDEX       (4UL)

#define LYS_MSG_NO_PARAM_LEN       (2UL)


static uint8_t       m_buf[LYS_MAX_MSG_LEN];
static const uint8_t m_ack_buf[LYS_MSG_NO_PARAM_LEN] = {LYS_MSG_NO_PARAM_LEN,
                                                           LYS_OP_ACK};

static uint8_t       m_buf_index = 0;
static lys_state_t   m_state     = LYS_STATE_UNKNOWN;
static bool          m_error     = false;

static lys_str_t     m_str;
static lys_array_t   m_array;
static lys_param_t   m_param;


static lys_error_t verify_array_len(lys_array_t *p_array, uint32_t *p_data_len)
{
    lys_error_t err;

    if (NULL == p_array)
    {
        return LYS_ERROR_INVALID_PARAM;
    }

    if (0 == p_array->item_count)
    {
        // Lys arrays need to have at least one item.
        return LYS_ERROR_INVALID_PARAM;
    }

    err = lys_param_len_lookup(p_array->param_type, p_data_len);
    if (LYS_ERROR_SUCCESS != err)
    {
        return err;
    } else if (LYS_PARAM_VARIABLE_SIZE == *p_data_len)
    {
        // Nested arrays and strings are not allowed.
        return LYS_ERROR_INVALID_PARAM;
    }

    *p_data_len *= p_array->item_count;
    if (LYS_MAX_MSG_LEN < (LYS_ARRAY_DATA_INDEX + *p_data_len))
    {
        // The array is too long.
        return LYS_ERROR_INVALID_PARAM;
    }
    return LYS_ERROR_SUCCESS;
}


static lys_error_t verify_str_len(lys_str_t *p_str, uint32_t *p_data_len)
{
    if (NULL == p_str)
    {
        return LYS_ERROR_INVALID_PARAM;
    }

    if (0 == p_str->len)
    {
        // Lys strings can't be empty.
        return LYS_ERROR_INVALID_PARAM;
    }

    *p_data_len = p_str->len;
    if (LYS_MAX_MSG_LEN < (LYS_DATA_INDEX + *p_data_len))
    {
        // The string is too long.
        return LYS_ERROR_INVALID_PARAM;
    }
    return LYS_ERROR_SUCCESS;
}


static lys_error_t param_add(const lys_param_t *p_param)
{
    lys_error_t       err;
    uint32_t          param_len;
    lys_param_type_t  param_type;
    uint8_t          *p_param_data;

    if (NULL == p_param)
    {
        return LYS_ERROR_INVALID_PARAM;
    }

    // A local copy is used so it can be overridden when adding arrays.
    param_type = p_param->param_type;

    err = lys_param_len_lookup(param_type, &param_len);
    if (LYS_ERROR_SUCCESS != err)
    {
        return err;
    }

    if (LYS_PARAM_VARIABLE_SIZE == param_len)
    {
        if (LYS_PARAM_TYPE_ARRAY == param_type)
        {
            lys_array_t *p_array = p_param->data.p_array;
            err = verify_array_len(p_array, &param_len);
            if (LYS_ERROR_SUCCESS != err)
            {
                return err;
            }
            m_buf[m_buf_index++] = LYS_PARAM_TYPE_ARRAY;
            param_type           = p_array->param_type;
            p_param_data         = p_array->data.p_uint8;
        }
        else if (LYS_PARAM_TYPE_STRING == param_type)
        {
            lys_str_t *p_str = p_param->data.p_str;
            err = verify_str_len(p_str, &param_len);
            if (LYS_ERROR_SUCCESS != err)
            {
                return err;
            }
            p_param_data = p_str->p_data;
        }
        else
        {
            return LYS_ERROR_INVALID_PARAM;
        }
    }
    else if (LYS_MAX_MSG_LEN < (LYS_DATA_INDEX + param_len))
    {
        // The data is too long.
        return LYS_ERROR_INVALID_PARAM;
    }
    else
    {
        p_param_data = p_param->data.p_uint8;
    }

    m_buf[m_buf_index++] = param_type;
    memcpy(&m_buf[m_buf_index], p_param_data, param_len);
    m_buf_index += param_len;

    return LYS_ERROR_SUCCESS;
}


static lys_error_t msg_create(lys_op_t op, const lys_param_t *p_param)
{
    lys_error_t err;

    m_buf_index          = LYS_OP_INDEX;
    m_buf[m_buf_index++] = op;

    switch (op)
    {
    case LYS_OP_UNKNOWN:
    case LYS_OP_INIT:
    case LYS_OP_START:
    case LYS_OP_RESULT:
    case LYS_OP_FINISHED:
    case LYS_OP_ACK:
        break;
    case LYS_OP_PARAM:
    case LYS_OP_LOG:
        if (LYS_ERROR_SUCCESS != (err=param_add(p_param)))
        {
            return err;
        }
        break;
    default:
        return LYS_ERROR_INVALID_PARAM;
    }
    m_buf[LYS_LEN_INDEX] = m_buf_index;
    return LYS_ERROR_SUCCESS;
}


static void msg_send(void)
{
    uint32_t bytes_written = 0;

    while (bytes_written < m_buf_index)
    {
        bytes_written += SEGGER_RTT_Write(LYS_RTT_CHANNEL,
            &m_buf[bytes_written],
            (m_buf_index - bytes_written));
    }
}


static void ack_msg_send(void)
{
    uint32_t bytes_written = 0;

    while (bytes_written < LYS_MSG_NO_PARAM_LEN)
    {
        bytes_written += SEGGER_RTT_Write(LYS_RTT_CHANNEL,
            &m_ack_buf[bytes_written],
            (LYS_MSG_NO_PARAM_LEN - bytes_written));
    }
}


static lys_error_t param_parse(void)
{
    lys_error_t err;
    uint32_t    param_len;
    uint32_t    data_len;

    if (LYS_PARAM_TYPE_ARRAY == m_buf[LYS_PARAM_TYPE_INDEX])
    {
        m_param.param_type   = LYS_PARAM_TYPE_ARRAY;
        m_param.data.p_array = &m_array;
        m_array.param_type   = m_buf[LYS_ARRAY_PARAM_TYPE_INDEX];

        data_len = (m_buf[LYS_LEN_INDEX] - LYS_ARRAY_DATA_INDEX);

        err = lys_param_len_lookup(m_array.param_type, &param_len);
        if (LYS_ERROR_SUCCESS != err)
        {
            return err;
        }

        if (0 != (data_len % param_len))
        {
            return LYS_ERROR_INVALID_PARAM;
        }

        m_array.item_count   = (data_len / param_len);
        m_array.data.p_uint8 = &m_buf[LYS_ARRAY_DATA_INDEX];
    }
    else
    {
        data_len = (m_buf[LYS_LEN_INDEX] - LYS_DATA_INDEX);

        if (LYS_PARAM_TYPE_STRING == m_buf[LYS_PARAM_TYPE_INDEX])
        {
            m_param.param_type = LYS_PARAM_TYPE_STRING;
            m_param.data.p_str = &m_str;

            m_str.len    = data_len;
            m_str.p_data = &m_buf[LYS_DATA_INDEX];
        }
        else
        {
            m_param.param_type   = m_buf[LYS_PARAM_TYPE_INDEX];
            m_param.data.p_uint8 = &m_buf[LYS_DATA_INDEX];

            err = lys_param_len_lookup(m_param.param_type, &param_len);
            if (LYS_ERROR_SUCCESS != err)
            {
                return err;
            }

            if (param_len != data_len)
            {
                return LYS_ERROR_INVALID_PARAM;
            }
        }
    }
    return LYS_ERROR_SUCCESS;
}


static lys_error_t msg_parse(lys_op_t *p_op, lys_param_t **p_param)
{
    lys_error_t err;

    *p_param = (lys_param_t*)NULL;
    *p_op    = m_buf[LYS_OP_INDEX];

    switch (*p_op)
    {
    case LYS_OP_UNKNOWN:
    case LYS_OP_INIT:
    case LYS_OP_START:
    case LYS_OP_RESULT:
    case LYS_OP_FINISHED:
    case LYS_OP_ACK:
        break;
    case LYS_OP_PARAM:
    case LYS_OP_LOG:
        if (LYS_ERROR_SUCCESS != (err=param_parse()))
        {
            return err;
        }
        *p_param = &m_param;
        break;
    default:
        return LYS_ERROR_INVALID_PARAM;
    }
    return LYS_ERROR_SUCCESS;
}


// Returns true if m_buf contains a complete lys message.
static bool msg_complete(void)
{
    if ((LYS_LEN_INDEX >= m_buf_index) || (m_buf[LYS_LEN_INDEX] > m_buf_index))
    {
        return false;
    }
    return true;
}


static lys_error_t msg_receive(lys_op_t *p_op, lys_param_t **p_param)
{
    m_buf_index = 0;

    while (!msg_complete())
    {
        m_buf_index += SEGGER_RTT_Read(LYS_RTT_CHANNEL,
            &m_buf[m_buf_index],
            (LYS_MAX_MSG_LEN - m_buf_index));
    }
    return msg_parse(p_op, p_param);
}


static lys_error_t wait_for_ack()
{
    lys_error_t  err;
    lys_op_t     op;
    lys_param_t *p_param;

    err = msg_receive(&op, &p_param);
    if (LYS_ERROR_SUCCESS != err)
    {
        return err;
    }

    if (LYS_OP_ACK != op)
    {
        return LYS_ERROR_INVALID_STATE;
    }
    return LYS_ERROR_SUCCESS;
}


static lys_error_t msg_send_and_ack(lys_op_t op, const lys_param_t *p_param)
{
    lys_error_t err = msg_create(op, p_param);
    if (LYS_ERROR_SUCCESS != err)
    {
        return err;
    }
    msg_send();
    return wait_for_ack();
}


static lys_error_t msg_receive_and_ack(lys_op_t *p_op, lys_param_t **p_param)
{
    lys_error_t err = msg_receive(p_op, p_param);
    if (LYS_ERROR_SUCCESS != err)
    {
        return err;
    }
    ack_msg_send();
    return LYS_ERROR_SUCCESS;
}


static void error(void)
{
    m_error = true;
    m_state = LYS_STATE_UNKNOWN;
}


static lys_error_t str_copy(lys_str_t *lhs, const lys_str_t *rhs)
{
    if ((rhs->len > LYS_MAX_STR_LEN) || (0 == rhs->len))
    {
        return LYS_ERROR_INVALID_PARAM;
    }
    lhs->len = rhs->len;
    memcpy(lhs->p_data, rhs->p_data, rhs->len);
    return LYS_ERROR_SUCCESS;
}


static lys_error_t array_copy(lys_array_t *lhs, const lys_array_t *rhs)
{
    lys_error_t      err;
    uint32_t         data_len;
    lys_param_type_t item_type = rhs->param_type;

    if (LYS_ERROR_SUCCESS != (err=lys_param_len_lookup(item_type, &data_len)))
    {
        return err;
    }

    if ((LYS_PARAM_VARIABLE_SIZE == data_len) || (0 == data_len))
    {
        // Array items have to have a fixed, non-zero length.
        return LYS_ERROR_INVALID_PARAM;
    }

    data_len *= rhs->item_count;
    if (data_len > LYS_MAX_ARRAY_LEN)
    {
        // The array is too long.
        return LYS_ERROR_INVALID_PARAM;
    }

    lhs->param_type = item_type;
    lhs->item_count = rhs->item_count;
    memcpy(lhs->data.p_uint8, rhs->data.p_uint8, data_len);
    return LYS_ERROR_SUCCESS;
}


void lys_init(void)
{
    m_buf_index = 0;
    m_state     = LYS_STATE_UNKNOWN;
    m_error     = false;
}


lys_state_t lys_state_get(void)
{
    return m_state;
}


bool lys_has_error(void)
{
    return m_error;
}


lys_error_t lys_param_wait(lys_param_t **p_param, bool *p_param_set)
{
    lys_error_t err;
    lys_op_t    op;

    if ((LYS_STATE_UNKNOWN == m_state) && (!m_error))
    {
        err = msg_send_and_ack(LYS_OP_INIT, NULL);
        if (LYS_ERROR_SUCCESS != err)
        {
            error();
            return err;
        }
        m_state = LYS_STATE_WAIT_FOR_START;
    }

    if (LYS_STATE_WAIT_FOR_START != m_state)
    {
        return LYS_ERROR_INVALID_STATE;
    }

    err = msg_receive_and_ack(&op, p_param);
    if (LYS_ERROR_SUCCESS != err)
    {
        error();
        return err;
    }

    switch (op)
    {
    case LYS_OP_START:
        *p_param_set = false;
        m_state      = LYS_STATE_RUNNING;
        break;
    case LYS_OP_PARAM:
        *p_param_set = true;
        break;
    case LYS_OP_UNKNOWN:
    case LYS_OP_INIT:
    case LYS_OP_LOG:    
    case LYS_OP_RESULT:
    case LYS_OP_FINISHED:
    case LYS_OP_ACK:
    default:
        *p_param_set = false;
        error();
        return LYS_ERROR_INVALID_STATE;
    }
    return LYS_ERROR_SUCCESS;
}


lys_error_t lys_params_receive(const lys_param_t *p_params, uint32_t param_count)
{
    lys_error_t  err;
    lys_param_t *p_received_param;
    bool         param_set;

    for (uint32_t i=0; i < param_count; i++)
    {
        lys_param_type_t  expected_type = p_params[i].param_type;
        uint8_t          *p_local_data  = p_params[i].data.p_uint8;
        uint32_t          param_len;

        err = lys_param_wait(&p_received_param, &param_set);
        if (LYS_ERROR_SUCCESS != err)
        {
            return err;
        }

        if (!param_set || (expected_type != p_received_param->param_type))
        {
            // Ran out of params too soon or wrong param type.
            return LYS_ERROR_INVALID_PARAM;
        }

        // Copy param data into the local buffer.
        switch (expected_type)
        {
        case LYS_PARAM_TYPE_UINT32:
        case LYS_PARAM_TYPE_INT32:
        case LYS_PARAM_TYPE_UINT8:
        case LYS_PARAM_TYPE_INT8:
        case LYS_PARAM_TYPE_BOOL:
            err = lys_param_len_lookup(expected_type, &param_len);
            if (LYS_ERROR_SUCCESS != err)
            {
                return err;
            }

            if (LYS_PARAM_VARIABLE_SIZE == param_len)
            {
                // These param types have a fixed length.
                return LYS_ERROR_INVALID_PARAM;
            }
            memcpy(p_local_data, p_received_param->data.p_uint8, param_len);
            break;
        case LYS_PARAM_TYPE_STRING:
            err = str_copy(p_params[i].data.p_str,
                p_received_param->data.p_str);
            if (LYS_ERROR_SUCCESS != err)
            {
                return err;
            }
            break;
        case LYS_PARAM_TYPE_ARRAY:
            err = array_copy(p_params[i].data.p_array,
                p_received_param->data.p_array);
            if (LYS_ERROR_SUCCESS != err)
            {
                return err;
            }
            break;
        default:
            // Don't know how to parse this parameter.
            return LYS_ERROR_INVALID_PARAM;
        }
    }

    // Wait for the start command. 
    err = lys_param_wait(&p_received_param, &param_set);
    if (LYS_ERROR_SUCCESS != err)
    {
        return err;
    }

    if (param_set)
    {
        // This means an extra param was encountered.
        error();
        return LYS_ERROR_INVALID_STATE;
    }
    return LYS_ERROR_SUCCESS;
}


lys_error_t lys_param_send(const lys_param_t *p_param)
{
    lys_error_t err;

    if (LYS_STATE_RUNNING == m_state)
    {
        err = msg_send_and_ack(LYS_OP_RESULT, NULL);
        if (LYS_ERROR_SUCCESS != err)
        {
            error();
            return err;
        }
        m_state = LYS_STATE_RESULT;
    }

    if (LYS_STATE_RESULT != m_state)
    {
        return LYS_ERROR_INVALID_STATE;
    }

    err = msg_send_and_ack(LYS_OP_PARAM, p_param);
    if (LYS_ERROR_SUCCESS != err)
    {
        error();
        return err;
    }
    return LYS_ERROR_SUCCESS;
}


lys_error_t lys_results_send(const lys_param_t *params, uint32_t param_count)
{
    lys_error_t  err;

    for (uint32_t i=0; i < param_count; i++)
    {
        err = lys_param_send(&params[i]);
        if (LYS_ERROR_SUCCESS != err)
        {
            return err;
        }
    }
    return lys_finish();
}


lys_error_t lys_finish(void)
{
    lys_error_t err;

    if (LYS_STATE_RUNNING == m_state)
    {
        err = msg_send_and_ack(LYS_OP_RESULT, NULL);
        if (LYS_ERROR_SUCCESS != err)
        {
            error();
            return err;
        }
        m_state = LYS_STATE_RESULT;
    }

    if (LYS_STATE_RESULT != m_state)
    {
        return LYS_ERROR_INVALID_STATE;
    }

    err = msg_send_and_ack(LYS_OP_FINISHED, NULL);
    if (LYS_ERROR_SUCCESS != err)
    {
        error();
        return err;
    }
    m_state = LYS_STATE_RESULT;
    return LYS_ERROR_SUCCESS;
}


lys_error_t lys_error_send()
{
    error();

    lys_error_t err = msg_create(LYS_OP_UNKNOWN, NULL);
    if (LYS_ERROR_SUCCESS != err)
    {
        return err;
    }
    msg_send();

    return wait_for_ack();
}


lys_error_t lys_log_send(const lys_str_t *p_str)
{
    lys_error_t err;

    if ((LYS_STATE_WAIT_FOR_START == m_state) || (LYS_STATE_RESULT == m_state))
    {
        return LYS_ERROR_INVALID_STATE;
    }

    m_param.param_type = LYS_PARAM_TYPE_STRING;
    m_param.data.p_str = (lys_str_t*) p_str;

    err = msg_send_and_ack(LYS_OP_LOG, &m_param);
    if (LYS_ERROR_SUCCESS != err)
    {
        error();
        return err;
    }
    return LYS_ERROR_SUCCESS;
}


lys_error_t lys_param_len_lookup(lys_param_type_t param_type, uint32_t *p_len)
{
    switch (param_type) {
    case LYS_PARAM_TYPE_UINT32:
        *p_len = sizeof(uint32_t);
        break;
    case LYS_PARAM_TYPE_INT32:
        *p_len = sizeof(int32_t);
        break;
    case LYS_PARAM_TYPE_UINT8:
        *p_len = sizeof(uint8_t);
        break;
    case LYS_PARAM_TYPE_INT8:
        *p_len = sizeof(int8_t);
        break;
    case LYS_PARAM_TYPE_BOOL:
        *p_len = sizeof(bool);
        break;
    case LYS_PARAM_TYPE_STRING:
    case LYS_PARAM_TYPE_ARRAY:
        *p_len = LYS_PARAM_VARIABLE_SIZE;
        break;
    default:
        return LYS_ERROR_INVALID_PARAM;
    }
    return LYS_ERROR_SUCCESS;
}
