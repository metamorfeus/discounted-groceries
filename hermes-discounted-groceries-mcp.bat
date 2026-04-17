@echo off
ssh -i C:\Users\PVELINOV\.ssh\hermes_contabo_openssh -p 2222 -o StrictHostKeyChecking=no -o BatchMode=yes hermes@62.146.169.66 "bash -l -c 'hermes -p discounted-groceries mcp serve'"
