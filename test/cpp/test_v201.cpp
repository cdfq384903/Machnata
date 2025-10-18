#include <iostream>
#include <string>
#include <fstream>
#include <google/protobuf/util/json_util.h>

#include "BootNotificationRequest.pb.h"

int main()
{
    // 測試的 JSON payload
    std::string json_input = R"({
        "chargingStation": {
            "firmwareVersion": "Unknown",
            "model": "Unknown",
            "serialNumber": "Unknown",
            "vendorName": "foxconn"
        },
        "reason": "PowerUp"
    })";

    // 建立一個 BootNotificationRequest 物件
    OCPP::v201::BootNotificationRequest request;

    // JSON -> Protobuf (反序列化)
    auto status = google::protobuf::util::JsonStringToMessage(json_input, &request);
    if (!status.ok())
    {
        std::cerr << "Failed to parse JSON: " << status.message() << std::endl;
        return -1;
    }

    // 印出反序列化後的結果
    std::cout << "Parsed BootNotificationRequest:" << std::endl;
    std::cout << "  FirmwareVersion: " << request.chargingstation().firmwareversion() << std::endl;
    std::cout << "  Model: " << request.chargingstation().model() << std::endl;
    std::cout << "  SerialNumber: " << request.chargingstation().serialnumber() << std::endl;
    std::cout << "  VendorName: " << request.chargingstation().vendorname() << std::endl;
    std::cout << "  Reason: " << request.reason() << std::endl;

    // Protobuf -> JSON (序列化)
    std::string json_output;
    google::protobuf::util::MessageToJsonString(request, &json_output);

    std::cout << "\nSerialized back to JSON:" << std::endl;
    std::cout << json_output << std::endl;

    return 0;
}
