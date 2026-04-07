#!/bin/bash
# Sproeituin installatie script voor Raspberry Pi
# Btechnics - Matthias Bogaert

echo "=== Sproeituin installatie ==="

# Installeer Python packages
pip3 install -r requirements.txt

# Kopieer script
sudo cp sproeituin.py /usr/local/bin/sproeituin.py
sudo chmod +x /usr/local/bin/sproeituin.py

# Maak systemd service
sudo tee /etc/systemd/system/sproeituin.service > /dev/null << EOF
[Unit]
Description=Sproeituin controller
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /usr/local/bin/sproeituin.py
Restart=always
RestartSec=5
User=pi

[Install]
WantedBy=multi-user.target
EOF

sudo systemctl daemon-reload
sudo systemctl enable sproeituin
sudo systemctl start sproeituin

echo "=== Installatie klaar ==="
echo "Status: sudo systemctl status sproeituin"
echo "Logs:   sudo journalctl -u sproeituin -f"
