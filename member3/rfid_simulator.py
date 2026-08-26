"""
Member 3: Virtual RFID Checkpoint Simulator Entrypoint Shim.
Re-exports RFIDReaderSimulator from member3.rfid.simulator.
"""

from member3.rfid.simulator import RFIDReaderSimulator

__all__ = ["RFIDReaderSimulator"]
