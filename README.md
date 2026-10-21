This is a working for me python vibe-coded application that solves a real world problem... for me. I hope others can use it.

I have four Bose SoundTouch 10 speakers and since the app was dropped from support I have been unable to use them. 

Linux install
You may need to instal python 3
Ubuntu & Debian
sudo apt update && sudo apt install -y python3-tk python3-pip
pip3 install requests

Fedora
sudo dnf install -y python3-tkinter python3-pip
pip3 install requests

Download this file into any location. Here is a sample.
git clone https://github.com/DuckDoolittle/Bose.git
cd Bose
python3 BoseController.py

Working
I have tested this with a four SoundTouch 10 speakers setup. 
Properly configured sets one of the speakers as a primary and the other three as slaves. 
Connecting bluetooth to that primary device will replicate the sound to the other three devices.

Next steps
Planning to enable multiple zones. starting with three.

Feel free to talk crap but if you do make it better is all I ask.

Cheers

