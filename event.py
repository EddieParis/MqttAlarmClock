from collections import deque

class Event:
    ROT_CW = const(0)
    ROT_CCW = const(1)
    ROT_PUSH = const(2)
    ROT_REL = const(3)
    KO_PUSH = const(4)
    KO_REL = const(5)
    TUNED = const(6)
    RDS_Basic_Tuning = const(7)
    RDS_Radio_Text = const(8)
    MODE_ENTER = const(9)
    TIMEOUT = const(10)
    SEEK_COMPLETE = const(11)
    EXIT = const(12)

    def __init__(self, event_type):
        self.type = event_type

class EventRotCwEvent(Event):
    def __init__(self, fast=False):
        super().__init__(Event.ROT_CW)
        self.fast = fast

class EventRotCcwEvent(Event):
    def __init__(self, fast=False):
        super().__init__(Event.ROT_CCW)
        self.fast = fast

class RadioTunedEvent(Event):
    def __init__(self, frequency, rssi, valid):
        super().__init__(Event.TUNED)
        self.frequency = frequency
        self.rssi = rssi
        self.valid = valid

class BasicTuningEvent(Event):
    def __init__(self, text):
        super().__init__(Event.RDS_Basic_Tuning)
        self.text = text

class RadioTextEvent(Event):
    def __init__(self, text):
        super().__init__(Event.RDS_Radio_Text)
        self.text = text

class EventsQueue:
    def __init__(self, event_flag):
        self.queue = deque((), 10)
        self.event_flag = event_flag

    def push(self, event):
        self.queue.append(event)
        self.event_flag.set()

    def pop(self):
        if len(self.queue) == 0:
            return None
        return self.queue.popleft()
