#
# This file is part of LiteX.
#
# Copyright (c) 2023-2024 Piotr Wegrzyn (Kuznia Rdzeni)
# SPDX-License-Identifier: BSD-2-Clause

import os
import subprocess

from migen import *

from litex import get_data_mod
from litex.soc.cores.cpu import CPU, CPU_GCC_TRIPLE_RISCV32
from litex.soc.interconnect import wishbone
from litex.soc.integration.soc import SoCRegion

# Variants -----------------------------------------------------------------------------------------

CPU_VARIANTS = {
        "minimal": "tiny",
        "standard": "basic",
        "full": "full",
}

# GCC Flags ----------------------------------------------------------------------------------------

GCC_FLAGS = {
    "minimal":          "-march=rv32e2p1                      -mabi=ilp32 ",
    "standard":         "-march=rv32i2p1_mazicsr_zifencei      -mabi=ilp32 ",
    "full":             "-march=rv32i2p1_maczicsr_zifencei   -mabi=ilp32 ",
}

# Coreblocks ----------------------------------------------------------------------------------------

class Coreblocks(CPU):
    category             = "softcore"
    family               = "riscv"
    name                 = "coreblocks"
    human_name           = "Coreblocks"
    variants             = CPU_VARIANTS
    data_width           = 32
    endianness           = "little"
    gcc_triple           = CPU_GCC_TRIPLE_RISCV32
    linker_output_format = "elf32-littleriscv"
    nop                  = "nop"
    io_regions           = {0xe000_0000: 0x2000_0000} # Origin, Length.

    # GCC Flags.
    @property
    def gcc_flags(self):
        flags =  GCC_FLAGS[self.variant]
        flags += "-D__coreblocks__ "
        return flags

    def __init__(self, platform, variant="standard"):
        self.platform     = platform
        self.variant      = variant
        self.human_name   = f"Coreblocks-{CPU_VARIANTS[variant]}"
        self.reset        = Signal()
        self.interrupt    = Signal(16) # hart-local 16 platform interrupts - ids 16+n

        self.ibus         = ibus = wishbone.Interface()
        self.dbus         = dbus = wishbone.Interface()
        self.periph_buses = [self.ibus, self.dbus] # Peripheral buses (Connected to main SoC's bus).
        self.memory_buses = []                     # Memory buses (Connected directly to LiteDRAM).

        # # #

        self.interrupts_full = Signal(32)
        # Shift interrupts to platform range
        self.comb += self.interrupts_full.eq(self.interrupt << 16)

        self.cpu_params = dict(
            # Clk / Rst.
            i_clk = ClockSignal("sys"),
            i_rst = ResetSignal("sys") | self.reset,

            ## IRQ.
            i_interrupts = self.interrupts_full,

            # Ibus.
            o_wb_instr__stb   = ibus.stb,
            o_wb_instr__cyc   = ibus.cyc,
            o_wb_instr__we    = ibus.we,
            o_wb_instr__adr   = ibus.adr,
            o_wb_instr__dat_w = ibus.dat_w,
            o_wb_instr__sel   = ibus.sel,
            i_wb_instr__ack   = ibus.ack,
            i_wb_instr__err   = ibus.err,
            i_wb_instr__dat_r = ibus.dat_r,

            # Dbus.
            o_wb_data__stb   = dbus.stb,
            o_wb_data__cyc   = dbus.cyc,
            o_wb_data__we    = dbus.we,
            o_wb_data__adr   = dbus.adr,
            o_wb_data__dat_w = dbus.dat_w,
            o_wb_data__sel   = dbus.sel,
            i_wb_data__ack   = dbus.ack,
            i_wb_data__err   = dbus.err,
            i_wb_data__dat_r = dbus.dat_r,
        )
        
        logcnt = Signal(5)
        req = ibus.stb & ibus.cyc & ibus.ack
        self.sync += If(req, logcnt.eq(logcnt+1))
        adrus = Signal(32)
        self.comb += adrus.eq(ibus.adr<<2)
        ddrus = Signal(32)
        self.comb += ddrus.eq(dbus.adr<<2)
        #self.sync += If((logcnt == 0) & (req), Display("[%0h]", adrus))
        if False:
            self.sync += If((req) & self.platform.trace, Display("[%0h]", adrus))
            self.sync += If(dbus.stb & dbus.cyc & dbus.ack & self.platform.trace, Display("<%0h %0h>", ddrus, dbus.dat_r))
            self.sync += If(ibus.stb & ibus.cyc & ibus.err, Display("!!![%0h]", adrus))
            self.sync += If(dbus.stb & dbus.cyc & dbus.err, Display("!!!<%0h>", ddrus))
    
    # Memory Mapping.
    @property
    def mem_map(self):
        # Default Memory Map.
        # In Coreblocks only clint address is fixed and MMIO (no-cache) region is set to 0xe000_0000 - 0xffff_fffff by default core configurations.
        # Other parameters are to arbitrary choice to LiteX. < TODO
        return {
            "rom":      0x0000_0000,
            "sram":     0x0100_0000,
            "main_ram": 0x4000_0000,
            "csr":      0xe000_0000,
            "clint":    0xe100_0000,
        }

    def add_soc_components(self, soc):
        soc.bus.add_region("clint", SoCRegion(origin=soc.mem_map.get("clint"), size=0xC000, cached=False, linker=True))

    def set_reset_address(self, reset_address):
        self.reset_address = reset_address
        assert reset_address == 0x0000_0000 #todo, but neorv32 does that

    @staticmethod
    def elaborate(variant, reset_address, verilog_filename):
        cli_params = []
        cli_params.append("--output={}".format(verilog_filename))
        cli_params.append("--config={}".format(CPU_VARIANTS[variant]))
        cli_params.append("--soc")
        #cli_params.append("--reset-addr={}".format(reset_address))
        sdir = get_data_mod("cpu", "coreblocks").data_location
        if subprocess.call(["python3", os.path.join(sdir, "scripts", "gen_verilog.py"), *cli_params]):
            print(["python3", os.path.join(sdir, "scripts", "gen_verilog.py"), *cli_params])
            raise OSError("Unable to elaborate Coreblocks CPU, please check your Amaranth/Yosys install")

    def do_finalize(self):
        assert hasattr(self, "reset_address")

        verilog_filename = os.path.join(self.platform.output_dir, "gateware", "core.v")
        self.elaborate(
            variant          = self.variant,
            reset_address    = self.reset_address,
            verilog_filename = verilog_filename)

        self.platform.add_source(verilog_filename)
        self.specials += Instance("top", **self.cpu_params)
