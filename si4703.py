import time
from machine import Pin

I2C_ADDRESS = 0x10

REG_DEVICE_ID = 0x00
REG_POWERCFG = 0x02
REG_CHANNEL = 0x03
REG_SYSCONFIG1 = 0x04
REG_SYSCONFIG2 = 0x05
REG_SYSCONFIG3 = 0x06
REG_TEST1 = 0x07
REG_STATUSRSSI = 0x0A
REG_READCHAN = 0x0B
REG_RDSA = 0x0C
REG_RDSB = 0x0D
REG_RDSC = 0x0E
REG_RDSD = 0x0F


class RDSB:
    RDS_A = 0
    RDS_B = 1
    RDS_C = 2
    RDS_D = 3



class BasicTuning(RDSB):
    def __init__(self):
        self.text = bytearray(8) # max of 8 chars
        self.complete = False
        self.segments_received = set()
        self.last_segment = 3  # default to max segments

    def process_data(self, block_kind, rds_blocks):
        segment = rds_blocks[RDSB.RDS_B] & 0x03
        self.segments_received.add(segment)
        self._add_data(segment*2, rds_blocks[RDSB.RDS_D])

        # check if we have all blocks
        if len(self.segments_received) >= self.last_segment + 1:
            self.complete = True

    def _add_data(self, index, block):
        c1 = (block >> 8) & 0xFF
        self.text[index] = c1
        c2 = block & 0xFF
        self.text[index + 1] = c2
        return c1, c2

    def get_text(self):
        res = self.text.decode("utf-8")
        return res

class RadioText(BasicTuning):
    def __init__(self, version):
        super().__init__()
        self.version = version
        self.text = bytearray(64)   # 16 * 4 bytes max
        self.last_segment = 15 # default to max segments

    def process_data(self, block_kind, rds_blocks):
        segment = rds_blocks[RDSB.RDS_B] & 0x0F
        if block_kind == 0:  # Text A
            # Each segment has 4 characters (2 from block C, 2 from block D
            self._add_data_A(segment, rds_blocks[RDSB.RDS_C], rds_blocks[RDSB.RDS_D])
        else: # Text B
            # Each segment has 2 characters from block D
            self._add_data_B(segment, rds_blocks[RDSB.RDS_D])

        self.segments_received.add(segment)

        # check if we have all blocks
        if len(self.segments_received) >= self.last_segment + 1:
            self.complete = True

    def _add_data_A(self, segment, blockC, blockD):
        index = segment * 4
        c1, c2 = self._add_data(index, blockC)
        c3, c4 = self._add_data(index+2, blockD)
        # check for end of text
        if c1 == 0x0D or c2 == 0x0D or c3 == 0x0D or c4 == 0x0D: # or (c1 == 0x020 and c2 == 0x020 and c3 == 0x020 and c4 == 0x020):
            self.last_segment = segment
            self.text = self.text[:4*(self.last_segment+1)+1]

    def _add_data_B(self, segment, blockD):
        index = segment * 2
        c1, c2 = self._add_data(index, blockD)
        # check for end of text
        if c1 == 0x0D or c2 == 0x0D: # or (c1 == 0x020 and c2 == 0x020):
            self.last_segment = segment
            self.text = self.text[:2*(self.last_segment+1)]

    def get_text(self):
        res = self.text.decode("utf-8")
        res = res.replace("/x0D", "")
        res.rstrip()
        return res

class SI4703:
    def __init__(self, i2c_bus, reset_pin, sen_pin, interrupt_pin=None):
        self.i2c = i2c_bus
        self.reset_pin = reset_pin
        self.interrupt_pin = interrupt_pin
        self.shadow_register = [0]*16

        self.rds_irq = None
        self.basic_tuning_handler = None
        self.tuned_irq = None
        self.seek_complete_irq = None
        self.radio_text_irq = None

        self.seek_in_progress = False
        self.seek_found_frequency = None

        self.radio_text = None
        self.basic_tuning = None

        self.old_radio_text_string = ""
        self.old_basic_tuning_string = ""

        #sen_pin.value(1)    # Enable I2C mode
        #Pin(2, Pin.OUT).value(0)

        # Reset the chip
        #self.reset_pin.value(0)
        #time.sleep(0.1)
        #self.reset_pin.value(1)
        #time.sleep(0.1)
        self._read_registers()

        # set initial configuration
        if self.interrupt_pin:
            self.interrupt_pin.irq(trigger=Pin.IRQ_FALLING, handler=self._irq_handler)
            self.shadow_register[REG_SYSCONFIG1] |= 0xC004  # Enable interrupts and interrupt pin (GPIO2)
            self._write_registers(REG_SYSCONFIG1)

        # Set europe config as default
        self.shadow_register[REG_SYSCONFIG1] |= 0x0800  # Set to De-emphasis 50us
        self.shadow_register[REG_SYSCONFIG2] |= 0x0010  # Set to 87.5MHz, 100kHz spacing
        self._write_registers(REG_SYSCONFIG2) # write from REG_POWERCFG to REG_SYSCONFIG2

    def _irq_handler(self, pin):
        self._read_registers(REG_STATUSRSSI)
        status = self.shadow_register[REG_STATUSRSSI]

        if status & 0x8000:  # RDS ready
            self._read_registers(REG_RDSD)
            block_type = (self.shadow_register[REG_RDSB] >> 12) & 0x0F
            block_kind = (self.shadow_register[REG_RDSB] >> 11) & 0x01
            block_version = (self.shadow_register[REG_RDSB] >> 4) & 0x01
            # Basic tuning (0x00)
            if block_type == 0x00:
                if self.basic_tuning == None:
                    self.basic_tuning = BasicTuning()
                self.basic_tuning.process_data(block_kind, self.shadow_register[REG_RDSA:REG_RDSD+1])
                if self.basic_tuning.complete and self.basic_tuning_handler:
                    text = self.basic_tuning.get_text()
                    if text != self.old_basic_tuning_string:
                        self.basic_tuning_handler(text)
                        self.basic_tuning = None
            # Radio text only (0x02)
            elif block_type == 0x02:
                if self.radio_text is None or self.radio_text.version != block_version:
                    self.radio_text = RadioText(block_version)
                self.radio_text.process_data(block_kind, self.shadow_register[REG_RDSA:REG_RDSD+1])
                if self.radio_text.complete and self.radio_text_irq:
                    text = self.radio_text.get_text()
                    if text != self.old_radio_text_string:
                        self.radio_text_irq(text)
                        self.radio_text = None
            if self.rds_irq:
                self.rds_irq()
            # Clear the interrupt flag
            #self.shadow_register[REG_STATUSRSSI] |= 0x8000
            #self._write_registers(REG_STATUSRSSI)

        if status & 0x4000:  # Seek/Tune complete
            if self.seek_in_progress:
                if status & 0x2000: # SEEK reached limit
                    self.seek_in_progress = False
                    if self.seek_complete_irq:
                        self.seek_complete_irq(self.seek_found_frequency)
                    # Clear the interrupt flag
                    self.shadow_register[REG_POWERCFG] &= ~0x0100  # Clear SEEK bit
                    self._write_registers(REG_POWERCFG)
                    return

                #get the found channel
                self._read_registers(REG_READCHAN)
                readchan = self.shadow_register[REG_READCHAN]
                frequency = 87.5 + (readchan & 0x03FF) / 10.0
                self.seek_found_frequency.append(frequency)

                # Clear the interrupt flag
                self.shadow_register[REG_POWERCFG] &= ~0x0100  # Clear SEEK bit
                self._write_registers(REG_POWERCFG)

                self.radio_text = None
                self.basic_tuning = None
                self.enable_rds(True)  # re-enable RDS after seek

                #self.seek_all()  # continue seeking
            else:
                self.seek_in_progress = False
                # Clear the interrupt flag
                self.shadow_register[REG_CHANNEL] &= ~0x8000  # Clear TUNE bit
                self._write_registers(REG_CHANNEL)
                self.shadow_register[REG_POWERCFG] &= ~0x0100  # Clear SEEK bit
                self._write_registers(REG_POWERCFG)
                #get the found channel
                self._read_registers(REG_READCHAN)
                frequency = 87.5 + (self.shadow_register[REG_READCHAN] & 0x03FF) / 10.0
                if self.tuned_irq:
                    self.tuned_irq(frequency, self.shadow_register[REG_STATUSRSSI] & 0xFF)

    def set_rds_irq(self, handler):
        self.rds_irq = handler

    def set_basic_tuning_handler(self, handler):
        self.basic_tuning_handler = handler

    def set_tuned_irq(self, handler):
        self.tuned_irq = handler

    def set_seek_complete_irq(self, handler):
        self.seek_complete_irq = handler

    def set_radio_text_irq(self, handler):
        self.radio_text_irq = handler

    def power_cristal(self, on=True):
        # Power up the crystal oscillator
        if on:
            self.shadow_register[REG_TEST1] |= 0x8100  # Set XOSCEN bit
        else:
            self.shadow_register[REG_TEST1] &= ~0x8000  # Clear XOSCEN bit
        self._write_registers(REG_TEST1)
        if on:
            time.sleep(0.5)  # Wait for crystal to stabilize

    def mute(self, on=True):
        # Mute or unmute audio
        if on: 
            self.shadow_register[REG_POWERCFG] &= ~0x4000  # Clear DMUTE bit
        else:
            self.shadow_register[REG_POWERCFG] |= 0x4000  # Set DMUTE bit
        self._write_registers(REG_POWERCFG)

    def enable(self, on=True):
        # enable or disable chip
        if on:
            self.shadow_register[REG_POWERCFG] |= 0x0001  # Set ENABLE bit
        else:
            self.shadow_register[REG_POWERCFG] &= ~0x0001  # Clear ENABLE bit
        self._write_registers(REG_POWERCFG)
        if on:
            time.sleep(0.1)  # Wait for powerup

    def set_frequency(self, frequency):
        # Set the frequency in MHz
        channel = int(frequency*10 - 875)  # Assuming 100kHz spacing
        self.shadow_register[REG_CHANNEL] &= ~0x83FF  # Clear TUNE bit and channel
        self.shadow_register[REG_CHANNEL] |= 0x8000 + (channel & 0x03FF) # Set TUNE bit and channel
        self._write_registers(REG_CHANNEL)

    def set_volume(self, volume):
        # Set volume level (0-15)
        volume = max(0, min(15, volume))  # Clamp volume to 0-15
        self.shadow_register[REG_SYSCONFIG2] = (self.shadow_register[REG_SYSCONFIG2] & ~0x000F) | volume
        self.shadow_register[REG_SYSCONFIG3] |= 0x0100  # Set VOLUME bit
        self._write_registers(REG_SYSCONFIG3)

    def enable_rds(self, on=True):
        # Enable or disable RDS
        if on:
            self.shadow_register[REG_SYSCONFIG1] |= 0x1000  # Set RDS bit
        else:
            self.shadow_register[REG_SYSCONFIG1] &= ~0x1000  # Clear RDS bit
        self._write_registers(REG_SYSCONFIG1)

    def seek_all(self, rssi_min=20):
        if not self.seek_in_progress:
            self.seek_found_frequency = []
            # Start seek from lowest frequency
            self.set_frequency(87.5)
            self.seek_in_progress = True
            #set interrupt flag for seek complete
            if self.interrupt_pin:
                self.shadow_register[REG_SYSCONFIG1] |= 0x4000  # Enable SEEK complete interrupt
                self._write_registers(REG_SYSCONFIG1)
            # set rssi minimum
            self.shadow_register[REG_SYSCONFIG2] &= ~0x00FF  # Clear RSSI bits
            self.shadow_register[REG_SYSCONFIG2] |= rssi_min<<8 # Set RSSI threshold
            self._write_registers(REG_SYSCONFIG2)
        self.seek_up(False)

    def seek_up(self, wrap=True):
        self.enable_rds(False)  # Disable RDS during seek
        self.radio_text = None
        self.basic_tuning = None
        # Seek upwards
        self.shadow_register[REG_POWERCFG] |= 0x0300 + (0x0400 if wrap else 0x0000)  # Set SEEKMODE, SEEK and SEEKUP bit
        self._write_registers(REG_POWERCFG)

    def seek_down(self):
        self.enable_rds(False)  # Disable RDS during seek
        self.radio_text = None
        self.basic_tuning = None
        # Seek downwards
        self.shadow_register[REG_POWERCFG] &= ~0x0200  # Clear SEEKUP bit
        self.shadow_register[REG_POWERCFG] |= 0x0500  # Set SEEKMODE and SEEK bit
        self._write_registers(REG_POWERCFG)

    def get_rssi(self):
        self._read_registers(REG_STATUSRSSI)
        status = self.shadow_register[REG_STATUSRSSI]
        rssi = status & 0xFF
        return rssi

    def update_shadow_register(self, shad_reg, reg_no, low_bit, high_bit, value):
        # Added by Dave Jaffe
        # Set shadow_register values
        # Use low_bit, high_bit from Si4702-03-C19 spec
        # For example, to set CHANNEL (Reg 3 [0-9]) update_shadow_register(shadow_register, 3, 0, 9, channel)
        # We will combine high and low bytes since Silicon Labs register spec refers to entire 16-bit word

        # shadow_register layout: Reg 2 high, 2 low, ... 7 high, 7 low (only Reg 2 - 7 are writeable)
        # The mapping between a register number reg_no and the location of its high byte in shadow_register is
        ind = (reg_no-2) * 2
        H = shad_reg[ind]      # Register high byte
        L = shad_reg[ind + 1]  # Register low byte
        W = 256*H + L     # Register 16-bit word
        # print(format(W, '016b'))
        # First, set bits where new value will go to 0 with a negative mask
        mask_len = high_bit - low_bit + 1
        mask = 2**mask_len - 1
        mask = mask << low_bit
        W = W & ~mask
        # Next, move new value to proper bit and add it to W
        V = value << low_bit
        W = W  + V
        # Break up W into H and L and write to shadow_register
        H = W >> 8
        L = W & 2**8 - 1 
        shad_reg[ind] = H
        shad_reg[ind + 1] = L

    def _read_registers(self, top_register=0x09):
        if top_register > 0x0F:
            raise ValueError("top_register must be between 0x00 and 0x0F")

        nb_registers = 6+top_register+1 if top_register < 0x0a else top_register - 0x0a + 1
        read_len = nb_registers * 2

        # read starts at register 0x0A and reads 32 bytes (16 registers)
        temp = self.i2c.readfrom(I2C_ADDRESS, read_len)
        # temp[0-1] = Reg 0A, temp[2-3] = Reg 0B, ..., temp[30-31] = Reg 19
        for i in range(nb_registers):
            self.shadow_register[(i+0x0a)%16] = (temp[2*i] << 8) | temp[2*i + 1]

    def _write_registers(self, top_register):
        # Write registers from 0x02 up to top_register
        if top_register < 2 or top_register > 7:
            raise ValueError("top_register must be between 2 and 7")

        # write starts at register 0x02 and writes up to register 0x07
        temp = bytearray()
        for i in range(2, top_register + 1):
            temp.append(self.shadow_register[i] >> 8)    # High byte
            temp.append(self.shadow_register[i] & 0x00FF)  # Low byte

        self.i2c.writeto(I2C_ADDRESS, temp)
