/* Copyright (c) 2014 Nordic Semiconductor. All Rights Reserved.
 *
 * The information contained herein is property of Nordic Semiconductor ASA.
 * Terms and conditions of usage are described in detail in NORDIC
 * SEMICONDUCTOR STANDARD SOFTWARE LICENSE AGREEMENT.
 *
 * Licensees are granted free, non-transferable use of the information. NO
 * WARRANTY of ANY KIND is provided. This heading must NOT be removed from
 * the file.
 *
 */
#include <stdbool.h>
#include <stdint.h>
#include "nrf_delay.h"
#include "nrf_gpio.h"
#include "boards.h"

#include "lys.h"


static const uint8_t m_leds_list[LEDS_NUMBER] = LEDS_LIST;

static uint32_t m_param_num_loops;
static uint8_t  m_param_blink_delay_type;
static uint32_t m_result;

static const lys_param_t m_params[] = {
    {.param_type=LYS_PARAM_TYPE_UINT32, .data.p_uint32=&m_param_num_loops},
    {.param_type=LYS_PARAM_TYPE_UINT8,  .data.p_uint8=&m_param_blink_delay_type}
};


static const lys_param_t m_results[] = {
    {.param_type=LYS_PARAM_TYPE_UINT32, .data.p_uint32=&m_result},
};


/**
 * @brief Function for application main entry.
 */
int main(void)
{
    // Configure LED-pins as outputs.
    LEDS_CONFIGURE(LEDS_MASK);

    lys_init();
    if (LYS_ERROR_SUCCESS != lys_params_receive(&m_params[0],
        (sizeof(m_params)/sizeof(lys_param_t))))
    {
        while (true)
        {
            lys_error_send();
        }
    }

    for (uint32_t j=0; j < m_param_num_loops; j++)
    {
        for (int i=0; i < LEDS_NUMBER; i++)
        {
            LEDS_INVERT(1 << m_leds_list[i]);
            switch (m_param_blink_delay_type)
            {
            case 0:
                nrf_delay_ms(100);
                break;
            case 1:
                nrf_delay_ms(500);
                break;
            case 2:
                nrf_delay_ms(1000);
                break;
            default:
                break;
            }
        }
    }

    m_result = (m_param_num_loops * m_param_blink_delay_type);
    if (LYS_ERROR_SUCCESS != lys_results_send(&m_results[0],
        (sizeof(m_results)/sizeof(lys_param_t))))
    {
        while (true)
        {
            lys_error_send();
        }
    }

    while (true)
    {
        // Finished.
    }
}

/** @} */
