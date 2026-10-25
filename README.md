This is a working for me python vibe-coded application that solves a real world problem... for me. I hope others can use it.

I have four Bose SoundTouch 10 speakers and since the app was dropped from support I have been unable to use them. 

Linux install:

You may need to install python 3:

Ubuntu & Debian:

sudo apt update && sudo apt install -y python3-tk python3-pip
pip3 install requests

Fedora:

sudo dnf install -y python3-tkinter python3-pip
pip3 install requests

Download this file into any location. 

git clone https://github.com/DuckDoolittle/BST10HLPR.git

cd BST10HLPR

python3 BST10HLPR.py

Working

I have tested this with a four SoundTouch 10 speakers setup. 
Properly configured sets one of the speakers as a primary and the other three as slaves. 
Connecting bluetooth to that primary device will replicate the sound to the other three devices.
Suppots 20 speakers 5 Zones 
Master IP is not selectible in Slave panel once selected as the master

Recent

Removed Zones - no need for them just select the priamary speaker IP and a slave and sync then select a new master and slaves and sunc those. Connect bluetooth device to primary speaker you will need to match the blutooth network and to the IP. 

Added dark mode by default
Added removal of IP
Added Forgotten IP tab and added features


Next steps

Make it look cool!!!!

Feel free to talk crap but if you do make it better, this is all I ask.

Cheers

