'''
Displays device indicies for all connected input/output devices
'''

import pyaudio as pa


# instantiate PyAudio
p = pa.PyAudio()
# find number of devices (input and output)
numDevices = p.get_device_count()

#print(f"{p.get_default_output_device_info()}")     # shows available options for .get()

def outputs():
    print("Output Devices:")
    for i in range(0, numDevices):

        if p.get_device_info_by_index(i).get('maxOutputChannels') != 0:
            print(f"{i}: ", end="")
            print(f"{p.get_device_info_by_index(i).get('name')}")




def inputs():
    print("Input Devices:")
    for i in range(0, numDevices):
        if p.get_device_info_by_index(i).get('maxInputChannels') != 0:
            print(f"{i}: ", end="")
            print(f"{p.get_device_info_by_index(i).get('name')}")

outputs()
inputs()