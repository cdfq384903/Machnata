SUMMARY = "OCPP schema + protobuf-c v1.6 test"
LICENSE = "CLOSED"

SRC_URI = "change to your source uri"

SRCREV_main = "${AUTOREV}"

S = "${WORKDIR}/git"
B = "${WORKDIR}/build"

# host 端生成器 + target 端 headers/libs
DEPENDS += "protobuf-c-native protobuf-native protobuf-c pkgconfig-native"

inherit pkgconfig

do_generate() {
    install -d ${S}/output/gen/c_out/ocpp/v16
    cd ${S}/output/proto/OCPP/v16
    export PATH=${STAGING_BINDIR_NATIVE}:$PATH
    if [ -x "${STAGING_BINDIR_NATIVE}/protoc-c" ]; then
        ${STAGING_BINDIR_NATIVE}/protoc-c -I . --c_out=${S}/output/gen/c_out/ocpp/v16 $(find . -name "*.proto")
    else
        ${STAGING_BINDIR_NATIVE}/protoc -I . --plugin=protoc-gen-c=${STAGING_BINDIR_NATIVE}/protoc-gen-c \
            --c_out=${S}/output/gen/c_out/ocpp/v16 $(find . -name "*.proto")
    fi
}
addtask generate after do_patch before do_compile

# 確保 protobuf-c 的 pc/headers/libs 都已在 sysroot
do_compile[depends] += "protobuf-c:do_populate_sysroot"

do_compile() {
    ls
    cd ${WORKDIR}/git/test/c/
    make 
    
}

do_install() {
    install -d ${D}${bindir}
    install -m 0755 ${S}/test/c/test_v16 ${D}${bindir}
}

FILES:${PN} += "${bindir}/test_v16"
RDEPENDS:${PN} += "protobuf-c"
