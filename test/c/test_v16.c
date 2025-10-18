#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <stdint.h>
#include <protobuf-c/protobuf-c.h>

#include "../../output/gen/c_out/ocpp/v16/BootNotification.pb-c.h"
#include "../../output/gen/c_out/ocpp/v16/StatusNotification.pb-c.h"
#include "../../output/gen/c_out/ocpp/v16/types/enums/StatusNotification_errorCode_enum.pb-c.h"
#include "../../output/gen/c_out/ocpp/v16/types/enums/StatusNotification_status_enum.pb-c.h"

/* ---------- tiny JSON helpers (toy, for demo only) ---------- */
static char *extract_json_value(const char *json, const char *key)
{
    char pattern[64];
    snprintf(pattern, sizeof(pattern), "\"%s\":\"", key);

    char *start = strstr(json, pattern);
    if (!start)
        return NULL;
    start += strlen(pattern);

    char *end = strchr(start, '"');
    if (!end)
        return NULL;

    size_t len = (size_t)(end - start);
    char *value = (char *)malloc(len + 1);
    if (!value)
        return NULL;

    strncpy(value, start, len);
    value[len] = '\0';
    return value;
}

static int extract_json_int(const char *json, const char *key)
{
    char pattern[64];
    snprintf(pattern, sizeof(pattern), "\"%s\":", key);
    char *start = strstr(json, pattern);
    if (!start)
        return 0;
    start += strlen(pattern);
    return atoi(start);
}

/* ---------- enum helpers ---------- */
static int enum_from_name(const ProtobufCEnumDescriptor *desc,
                          const char *name,
                          int default_val)
{
    if (!desc || !name || !*name)
        return default_val;
    const ProtobufCEnumValue *v =
        protobuf_c_enum_descriptor_get_value_by_name(desc, name);
    return v ? (int)v->value : default_val;
}

/* ---------- demos ---------- */

void deserialize_boot(void)
{
    const char *input_json =
        "{\"chargePointVendor\":\"test_Vendor\",\"firmwareVersion\":\"66.69.99\",\"chargePointModel\":\"test_Model\"}";

    printf("Incoming JSON:\n%s\n\n", input_json);

    OCPP__V16__BootNotification msg = OCPP__V16__BOOT_NOTIFICATION__INIT;

    char *vendor = extract_json_value(input_json, "chargePointVendor");
    char *model = extract_json_value(input_json, "chargePointModel");
    char *firmware = extract_json_value(input_json, "firmwareVersion");

    msg.chargepointvendor = vendor ? vendor : (char *)"";
    msg.chargepointmodel = model ? model : (char *)"";
    msg.firmwareversion = firmware ? firmware : (char *)"";

    printf("Deserialized BootNotification:\n");
    printf("  chargePointVendor : %s\n", msg.chargepointvendor);
    printf("  chargePointModel  : %s\n", msg.chargepointmodel);
    printf("  firmwareVersion   : %s\n", msg.firmwareversion);

    free(vendor);
    free(model);
    free(firmware);
}

int serialize_boot(void)
{
    OCPP__V16__BootNotification msg = OCPP__V16__BOOT_NOTIFICATION__INIT;

    msg.chargepointvendor = "Vendor_test_serialize1";
    msg.chargepointmodel = "Model_test_serialize2";
    msg.firmwareversion = "FW_test_serialize3";

    char json_str[256];
    snprintf(json_str, sizeof(json_str),
             "{\"chargePointVendor\":\"%s\",\"chargePointModel\":\"%s\",\"firmwareVersion\":\"%s\"}",
             msg.chargepointvendor,
             msg.chargepointmodel,
             msg.firmwareversion);

    printf("\nSerialized JSON string:\n%s\n", json_str);
    return 0;
}

void deserialize_status(void)
{
    const char *json_str =
        "{\"connectorId\":1,\"errorCode\":\"NoError\",\"status\":\"Faulted\",\"timestamp\":\"2025-04-02T16:34:36Z\"}";

    printf("Incoming JSON:\n%s\n\n", json_str);

    OCPP__V16__StatusNotification msg = OCPP__V16__STATUS_NOTIFICATION__INIT;

    msg.connectorid = extract_json_int(json_str, "connectorId");

    char *error_code = extract_json_value(json_str, "errorCode");
    char *status = extract_json_value(json_str, "status");
    char *timestamp = extract_json_value(json_str, "timestamp");

    /* 把名稱轉 enum 值；找不到就用 0 (UNSPECIFIED) */
    msg.errorcode = enum_from_name(
        &ocpp__v16__types__enums__statusnotification_errorcode_enum__status_notification_error_code_enum__descriptor,
        error_code, 0);

    msg.status = enum_from_name(
        &ocpp__v16__types__enums__statusnotification_status_enum__status_notification_status_enum__descriptor,
        status, 0);

    msg.timestamp = timestamp ? timestamp : (char *)"";

    printf("Deserialized StatusNotification:\n");
    printf("  connectorId : %d\n", msg.connectorid);
    printf("  errorCode   : %d\n", msg.errorcode);
    printf("  status      : %d\n", msg.status);
    printf("  timestamp   : %s\n", msg.timestamp);

    size_t packed_size = ocpp__v16__status_notification__get_packed_size(&msg);
    uint8_t *buffer = (uint8_t *)malloc(packed_size);
    if (buffer)
    {
        ocpp__v16__status_notification__pack(&msg, buffer);
        printf("\nSerialized protobuf size: %zu bytes\n", packed_size);

        OCPP__V16__StatusNotification *unpacked =
            ocpp__v16__status_notification__unpack(NULL, packed_size, buffer);
        if (unpacked)
        {
            printf("\nUnpacked from binary:\n");
            printf("  connectorId : %d\n", unpacked->connectorid);
            printf("  errorCode   : %d\n", unpacked->errorcode);
            printf("  status      : %d\n", unpacked->status);
            printf("  timestamp   : %s\n", unpacked->timestamp);
            ocpp__v16__status_notification__free_unpacked(unpacked, NULL);
        }
        free(buffer);
    }

    free(error_code);
    free(status);
    free(timestamp);
}

int main(void)
{
    deserialize_boot();
    serialize_boot();
    // 需要時再打開：
    // deserialize_status();
    return 0;
}
