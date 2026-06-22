# Ralph Security Guide

> "It's not IF it gets popped, it's WHEN. What's the blast radius?"

## The Lethal Trifecta

When you run `--dangerously-skip-permissions`, the model has:

1. **Access to do things** (execute any command)
2. **Access to the network** (can reach external services)
3. **Access to whatever data is on the machine**

If all three combine with malicious input or model error, bad things happen.

## Real Risks

### On Your Local Laptop

If you run Ralph with full permissions on your personal computer:

| Asset | Risk | How |
|-------|------|-----|
| Browser cookies | Stolen | Model reads ~/.config/chrome/ |
| SSH keys | Exfiltrated | Model reads ~/.ssh/ |
| API keys | Used/leaked | Model reads ~/.env, ~/.aws/, etc. |
| Crypto wallets | Drained | Model accesses wallet files |
| Personal files | Read/sent | Model can read and curl anywhere |
| GitHub access | Compromised | Model uses your git credentials |

**This is not theoretical.** The model has shell access. It can do anything you can do.

### Attack Vectors

1. **Prompt injection in fetched content**
   - Model fetches a webpage for research
   - Webpage contains hidden instructions
   - Model follows malicious instructions

2. **Malicious dependencies**
   - Model runs `npm install`
   - Package has postinstall script
   - Script runs arbitrary code

3. **Model hallucination**
   - Model decides it needs to "back up" your files
   - Sends them somewhere unexpected

4. **Confused context**
   - Long context window gets muddled
   - Model misinterprets destructive command as helpful

## The Solution: Blast Radius Engineering

Instead of preventing all attacks (impossible), minimize the damage when something goes wrong.

### Principle: Assume Breach

Design your Ralph environment as if it **will** be compromised. Then ask:
- What can the attacker access?
- What can they do?
- What's the worst case?

### The Ideal Setup

```
┌─────────────────────────────────────────────────────────┐
│                   YOUR LAPTOP                            │
│  - Personal files                                        │
│  - Browser sessions                                      │
│  - SSH keys to production                               │
│  - Crypto wallets                                        │
│  - Everything you care about                            │
│                                                          │
│  ❌ DO NOT RUN RALPH HERE                               │
└─────────────────────────────────────────────────────────┘
          │
          │ SSH (just for setup)
          ▼
┌─────────────────────────────────────────────────────────┐
│              EPHEMERAL VM (Ralph's Home)                │
│                                                          │
│  ✅ Only credentials:                                    │
│     - Anthropic API key (can only spend tokens)         │
│     - GitHub deploy key (can only push to ONE repo)     │
│                                                          │
│  ✅ No access to:                                        │
│     - Production systems                                 │
│     - Personal data                                      │
│     - Other repositories                                 │
│     - Sensitive services                                 │
│                                                          │
│  ✅ Network restricted (optional):                       │
│     - Allowlist of domains                               │
│     - No access to internal network                      │
│                                                          │
│  ✅ Destroyable:                                         │
│     - When done, delete the VM                          │
│     - All evidence of compromise deleted too            │
│                                                          │
└─────────────────────────────────────────────────────────┘
```

### Blast Radius: Before and After

| Scenario | Local Laptop | Ephemeral VM |
|----------|--------------|--------------|
| Model sends files externally | All personal data | Just this project's code |
| SSH key stolen | Access to prod, all repos | Access to one repo |
| API keys leaked | AWS bill, service access | Anthropic tokens only |
| Malware installed | Persistent on your machine | Gone when VM deleted |

## Setting Up an Ephemeral Environment

### Option 1: GCP VM

```bash
# Create
gcloud compute instances create ralph-worker \
  --machine-type=e2-medium \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud \
  --zone=us-central1-a

# SSH in
gcloud compute ssh ralph-worker

# Setup
curl -fsSL https://cli.anthropic.com/install.sh | sh
export ANTHROPIC_API_KEY="sk-ant-..."
git clone git@github.com:you/your-repo.git
cd your-repo

# Work
./ralph.sh

# Destroy when done
exit
gcloud compute instances delete ralph-worker
```

### Option 2: AWS EC2

```bash
# Create
aws ec2 run-instances \
  --image-id ami-0c55b159cbfafe1f0 \
  --instance-type t3.medium \
  --key-name your-key

# Connect, setup, work...

# Terminate
aws ec2 terminate-instances --instance-ids i-xxx
```

### Option 3: Docker Container

```bash
# Create isolated container
docker run -it --rm \
  -e ANTHROPIC_API_KEY="sk-ant-..." \
  -v $(pwd):/workspace \
  ubuntu:22.04 bash

# Inside container
apt update && apt install -y curl git
# Install Claude CLI, work, exit
# Container is destroyed on exit
```

### Option 4: GitHub Codespaces

```bash
# Create codespace from repo
# Work in browser-based VS Code
# Delete codespace when done
```

## Credential Minimization

### GitHub: Deploy Keys (Not Personal Token)

```bash
# Generate key for this repo only
ssh-keygen -t ed25519 -f ~/.ssh/ralph_deploy_key -N ""

# Add to repo as deploy key (Settings > Deploy Keys)
# Enable "Allow write access" if Ralph needs to push

# Configure git to use it
echo "Host github-ralph
  HostName github.com
  IdentityFile ~/.ssh/ralph_deploy_key
  IdentitiesOnly yes" >> ~/.ssh/config

# Clone with deploy key
git clone git@github-ralph:you/your-repo.git
```

**Deploy key can only access ONE repo.** If leaked, blast radius is one repo.

### API Keys: Scoped and Rotatable

- Use keys that can be rotated easily
- Set spending limits where possible
- Monitor usage for anomalies

### No Production Credentials

Never put production database passwords, AWS root keys, or admin tokens in your Ralph environment. Ever.

## Network Restrictions (Advanced)

### Egress Filtering

Limit what external hosts the VM can reach:

```bash
# Allow only specific domains
iptables -A OUTPUT -p tcp -d api.anthropic.com --dport 443 -j ACCEPT
iptables -A OUTPUT -p tcp -d github.com --dport 22 -j ACCEPT
iptables -A OUTPUT -p tcp -d registry.npmjs.org --dport 443 -j ACCEPT
iptables -A OUTPUT -j DROP
```

This prevents data exfiltration to arbitrary hosts.

### Private Networking

Run the VM in a VPC with no public IP:
- Access only through bastion/tunnel
- No inbound connections possible
- Egress through NAT gateway (can be filtered)

## What If You Must Run Locally?

If you absolutely cannot use a VM:

1. **Create a separate user account**
   ```bash
   sudo adduser ralph-worker
   # Give it no access to your home directory
   ```

2. **Use a VM within your laptop**
   - VirtualBox, VMware, or Parallels
   - Snapshot before, restore after

3. **Container with restricted mounts**
   ```bash
   docker run -it --rm \
     -v $(pwd):/workspace:rw \
     # No other mounts
     ubuntu:22.04
   ```

4. **Accept the risk consciously**
   - Document what could go wrong
   - Be prepared to rotate all credentials
   - Monitor for unusual activity

## Security Checklist

Before running Ralph:

- [ ] Running on isolated/ephemeral infrastructure
- [ ] No production credentials accessible
- [ ] No personal data accessible
- [ ] GitHub access via deploy key (not personal token)
- [ ] API keys are rotatable and monitored
- [ ] Network egress is understood/restricted
- [ ] Blast radius is documented and acceptable
- [ ] `.ralph-security` file is completed and signed

## Response Plan

If you suspect compromise:

1. **Immediately:**
   - Destroy the VM/container
   - Rotate any credentials that were on it

2. **Check:**
   - GitHub repo for unexpected commits
   - API usage for anomalies
   - Any services those credentials accessed

3. **Learn:**
   - What went wrong?
   - How to prevent next time?

## The Mantra

> "Blast radius engineering, not attack prevention."
> "Assume breach. Minimize damage."
> "Ephemeral environments are your friend."
> "Deploy keys, not personal tokens."
> "Destroy when done."
