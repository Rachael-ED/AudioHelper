'''
Displays device indicies for all connected input/output devices
'''

import pyaudio as pa

# instantiate PyAudio
p = pa.PyAudio()
# find number of devices (input and output)
numDevices = p.get_device_count()

for i in range(0, numDevices):
    print(f"Index: {i} ", end="")
    print(f"Device: {p.get_device_info_by_index(i).get('name')}")
