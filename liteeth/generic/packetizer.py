from liteeth.common import *

def _encode_header(h_dict, h_signal, obj):
	r = []
	for k, v in sorted(h_dict.items()):
		start = v.byte*8+v.offset
		end = start+v.width
		r.append(h_signal[start:end].eq(reverse_bytes(getattr(obj, k))))
	return r

class LiteEthPacketizer(Module):
	def __init__(self, sink_description, source_description, header_type, header_length):
		self.sink = sink = Sink(sink_description)
		self.source = source = Source(source_description)
		self.header = Signal(header_length*8)
		###
		dw = flen(self.sink.data)

		header_reg = Signal(header_length*8)
		load = Signal()
		shift = Signal()
		counter = Counter(max=header_length//(dw//8))
		self.submodules += counter

		self.comb += _encode_header(header_type, self.header, sink)
		self.sync += [
			If(load,
				header_reg.eq(self.header)
			).Elif(shift,
				header_reg.eq(Cat(header_reg[dw:], Signal(dw)))
			)
		]

		fsm = FSM(reset_state="IDLE")
		self.submodules += fsm

		fsm.act("IDLE",
			sink.ack.eq(1),
			counter.reset.eq(1),
			If(sink.stb & sink.sop,
				sink.ack.eq(0),
				source.stb.eq(1),
				source.sop.eq(1),
				source.eop.eq(0),
				source.data.eq(self.header[:dw]),
				If(source.stb & source.ack,
					load.eq(1),
					NextState("SEND_HEADER"),
				)
			)
		)
		fsm.act("SEND_HEADER",
			source.stb.eq(1),
			source.sop.eq(0),
			source.eop.eq(sink.eop & (counter.value == header_length//(dw//8)-2)),
			source.data.eq(header_reg[dw:2*dw]),
			If(source.stb & source.ack,
				shift.eq(1),
				counter.ce.eq(1),
				If(counter.value == header_length//(dw//8)-2,
					NextState("COPY")
				)
			)
		)
		fsm.act("COPY",
			source.stb.eq(sink.stb),
			source.sop.eq(0),
			source.eop.eq(sink.eop),
			source.data.eq(sink.data),
			source.error.eq(sink.error),
			If(source.stb & source.ack,
				sink.ack.eq(1),
				If(source.eop,
					NextState("IDLE")
				)
			)
		)
