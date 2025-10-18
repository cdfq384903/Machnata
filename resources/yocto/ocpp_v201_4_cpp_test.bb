SUMMARY = "OCPP schema + protobuf-c v2.0.1 test"
LICENSE = "CLOSED"

SRC_URI = "change to your source uri"

SRCREV_main = "${AUTOREV}"

S = "${WORKDIR}/git"
B = "${WORKDIR}/build"

# 開啟V201測試
EXTRA_OECMAKE = " \
    -DTEST_V201=ON \
"

# 依賴設置
DEPENDS += "protobuf protobuf-native abseil-cpp"

inherit cmake

# CMakeLists 在 test/cpp 目錄
OECMAKE_SOURCEPATH = "${S}/test/cpp"

# ===== 產生 .pb.h / .pb.cc  =====
do_generate() {
    # 生成目錄：與 README 一致 => ${S}/output/gen/cpp_out
    install -d ${S}/output/gen/cpp_out/ocpp/v201
    cd ${S}/output/proto/OCPP/v201

    # 用 host 端的 protoc 來產生（protobuf-native 提供）
    ${STAGING_BINDIR_NATIVE}/protoc -I=. --cpp_out=${S}/output/gen/cpp_out/ocpp/v201 \
        $(find . -name "*.proto" -print)
}
addtask generate after do_patch before do_configure

do_install() {
    install -d ${D}${bindir}
    
    install -m 0755 ${B}/test_v201 ${D}${bindir}/ocpp-v201-test
}

FILES:${PN} += "${bindir}/ocpp-v201-test"