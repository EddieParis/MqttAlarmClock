I2C_ADDRESS = 0x10

class SI4703:
    def __init__(self, i2c_bus, reset_pin, interrupt_pin=None):
        self.i2c = i2c_bus
        self.reset_pin = reset_pin
        self.interrupt_pin = interrupt_pin
        self.shadow_register = [0]*16

        self.rds_irq = None
        self.tuned_irq = None

        # Reset the chip
        self.reset_pin.value(0)
        time.sleep(0.1)
        self.reset_pin.value(1)
        time.sleep(0.1)
        self.read_registers()

        # set initial configuration
        if self.interrupt_pin:
            self.interrupt_pin.irq(trigger=Pin.IRQ_FALLING, handler=self._irq_handler)
            self.shadow_register[2] |= 0x0004  # Enable interrupt pin
            self.write_registers(2)
            self.shadow_register[10] |= 0x0040  # Enable interrupt
            self.write_registers(10)

        # Set europe config as default
        self.shadow_register[2] |= 0x0800  # Set to De-emphasis 50us
        self.shadow_register[5] |= 0x0010  # Set to 87.5MHz, 100kHz spacing
        self.write_registers(2)

    def _irq_handler(self, pin):
        pass

    def power_cristal(self, on=True):
        # Power up the crystal oscillator
        if on:
            self.shadow_register[7] |= 0x8000  # Set XOSCEN bit
        else:
            self.shadow_register[7] &= ~0x8000  # Clear XOSCEN bit
        self.write_registers(7)
        if on:
            time.sleep(0.5)  # Wait for crystal to stabilize

    def mute(self, on=True):
        # Mute or unmute audio
        if on:
            self.shadow_register[2] |= 0x4000  # Set DMUTE bit
        else:
            self.shadow_register[2] &= ~0x4000  # Clear DMUTE bit
        self.write_registers(2)

    def enable(self, on=True):
        # enable or disable chip
        if on:
            self.shadow_register[2] |= 0x0001  # Set ENABLE bit
        else:
            self.shadow_register[2] &= ~0x0001  # Clear ENABLE bit
        self.write_registers(2)

    def set_frequency(self, frequency):
        # Set the frequency in MHz
        channel = int((frequency - 87.5) * 10)  # Assuming 100kHz spacing
        self.shadow_register[3] |= channel & 0x03FF
        self.shadow_register[3] |= 0x8000  # Set TUNE bit
        self.write_registers(3)

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

    def read_registers(self):
        temp = self.i2c.readfrom(I2C_ADDRESS, 32)
        for i in range(16):
            self.shadow_register[i] = (temp[2*i] << 8) | temp[2*i + 1]

    def write_register(self, address, shad_reg, reg_no, low_bit, high_bit, value):
        reg = i2c.read_i2c_block_data(address, shad_reg[0], 32)
        shad_reg = reg[16:28]
        self.update_shadow_register(shad_reg, reg_no, low_bit, high_bit, value)
        i2c.write_i2c_block_data(address, shad_reg[0], shad_reg[1:])