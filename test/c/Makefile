PKG_CONFIG ?= pkg-config

CFLAGS  ?=
CFLAGS  += -Wall -Wextra -g
LDFLAGS ?=
LDLIBS  ?=

# protobuf-c (prefer pkg-config)
HAVE_PROTOBUF_C := $(shell $(PKG_CONFIG) --exists protobuf-c && echo yes || echo no)
ifeq ($(HAVE_PROTOBUF_C),yes)
CFLAGS  += $(shell $(PKG_CONFIG) --cflags protobuf-c)
LDLIBS  += $(shell $(PKG_CONFIG) --libs   protobuf-c)
else
LDLIBS  += -lprotobuf-c
endif

# -------- settings: choose spec/version (override via: `make VER=v21`) --------
SPEC ?= ocpp
VER  ?= v16

GEN_BASE := ../../output/gen/c_out
GEN_DIR  := $(GEN_BASE)/$(SPEC)/$(VER)

# test source
SRCS_TEST := test_v16.c

# auto-collect generated sources
SRCS_GEN  := \
  $(wildcard $(GEN_DIR)/*.pb-c.c) \
  $(wildcard $(GEN_DIR)/types/*.pb-c.c) \
  $(wildcard $(GEN_DIR)/types/enums/*.pb-c.c)

SRCS  := $(SRCS_TEST) $(SRCS_GEN)
OBJS  := $(SRCS:.c=.o)
TARGET := test_$(VER)

# include paths for generated headers
CFLAGS += -I$(GEN_DIR) -I$(GEN_DIR)/types -I$(GEN_DIR)/types/enums

all: $(TARGET)

$(TARGET): $(OBJS)
	$(CC) $(CFLAGS) $(LDFLAGS) $(OBJS) -o $@ $(LDLIBS)

# generic compile rule (works for both local and absolute-path sources)
%.o: %.c
	@mkdir -p $(dir $@)
	$(CC) $(CFLAGS) -c $< -o $@

clean:
	rm -f $(OBJS) $(TARGET)

run: $(TARGET)
	./$(TARGET)

.PHONY: all clean run
