# Ralph Security Sign-Off

> Complete this checklist before running Ralph with `--dangerously-skip-permissions`
> "Not IF it gets popped, but WHEN. What's the blast radius?"

## Date
[DATE]

## Environment Assessment

### Where is this running?

- [ ] **Local laptop** ⚠️ DANGEROUS
      - Has access to: browser cookies, SSH keys, wallets, personal files
      - Blast radius: HIGH - could compromise all accounts
      - Recommendation: Use ephemeral VM instead

- [ ] **Remote VM (persistent)**
      - Better isolation from personal data
      - Still has whatever credentials you put there
      
- [ ] **Ephemeral VM / Container** ✅ RECOMMENDED
      - Destroyed after use
      - Minimal credentials
      - Lowest blast radius

### Infrastructure Details
- Provider: [GCP / AWS / Azure / Local / Other]
- Instance type: [description]
- Network: [Public IP? VPC? Isolated?]

## Credentials Inventory

List ALL credentials accessible from this environment:

### API Keys
| Service | Key Type | Scope | Risk if Leaked |
|---------|----------|-------|----------------|
| [Anthropic] | [API Key] | [Claude access] | [Token spend] |
| [GitHub] | [Deploy Key] | [This repo only] | [Code push] |
| [???] | [???] | [???] | [???] |

### SSH Keys
| Key | Access To | Risk |
|-----|-----------|------|
| [???] | [???] | [???] |

### Auth Tokens / Cookies
| Service | Type | Risk |
|---------|------|------|
| [None - ephemeral env] | - | - |

## Blast Radius Assessment

If this environment is fully compromised, the attacker could:

1. [Describe worst-case scenario]
2. [What data could be accessed?]
3. [What systems could be pivoted to?]
4. [What actions could be taken?]

**Is this acceptable?** [ ] Yes [ ] No

## Network Access

- [ ] Full internet access (can reach any domain)
- [ ] Restricted egress (allowlist only)
- [ ] No external network access

**If full access:** Model could hit malicious sites, leak data externally.
**Mitigation:** [Describe any network restrictions in place]

## Private Data

Is there private/sensitive data accessible?

- [ ] Personal files (documents, photos, etc.)
- [ ] Credentials for other services
- [ ] Customer/user data
- [ ] Financial information
- [ ] None of the above ✅

## Sign-Off

I have reviewed the above and understand:

- [ ] The model will have full shell access in this environment
- [ ] If compromised, the blast radius is as documented above
- [ ] I accept this risk for the benefits of autonomous operation
- [ ] I will destroy/reset this environment when done (if ephemeral)

**Signed:** ____________________

**Date:** ____________________

---

## Quick Reference: Safe Setup

```bash
# 1. Create ephemeral VM (example: GCP)
gcloud compute instances create ralph-worker \
  --machine-type=e2-medium \
  --image-family=ubuntu-2204-lts \
  --image-project=ubuntu-os-cloud

# 2. SSH in
gcloud compute ssh ralph-worker

# 3. Install only what's needed
curl -fsSL https://claude.ai/install.sh | sh
# Clone your repo
# Set minimal API keys

# 4. Run Ralph
./ralph.sh

# 5. When done, DESTROY
gcloud compute instances delete ralph-worker
```

The best security is an environment you can delete.
