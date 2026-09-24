# Community Guide

## Where to Ask

There is no community chat server yet. No Discord, Slack or Telegram invite exists anywhere in this repository, and GitHub Discussions are turned off on it. Questions, bug reports and suggestions for the courses go to the repository's GitHub issues.

The norms that apply there:
- Be respectful. Technical disagreements are fine; personal attacks are not.
- No financial advice. Sharing knowledge about how DeFi works is encouraged. Telling someone to buy a specific token is not.
- No spam or self-promotion.

## Office Hours

There are no scheduled office hours.

## How to Run a Workshop

Community members are encouraged to run workshops for their teams, meetup groups, or local communities. Here is a template for a 2-hour workshop.

### Workshop Template Agenda

**Title**: Introduction to The Matrix -- Hands-On Workshop

**Duration**: 2 hours

**Prerequisites for Attendees**: Laptop with Python 3.11+ installed, internet connection, text editor

**Facilitator Prep**: Clone the repo, run setup.py, verify the gateway starts on your machine before the workshop.

| Time | Activity | Description |
|------|----------|-------------|
| 0:00-0:10 | Welcome and Setup | Verify all attendees have Python and git. Help with any installation issues. |
| 0:10-0:25 | What is The Matrix? | Present Module 01 content. Cover the three agents, the architecture, and the 195-capability catalog organized by category. |
| 0:25-0:45 | Live Setup | Everyone clones the repo, runs setup, and starts the gateway. Troubleshoot together. |
| 0:45-1:00 | First Interaction | Attendees send their first /chat request via curl. Discuss the response format. |
| 1:00-1:10 | Break | |
| 1:10-1:35 | Build a Plugin | Walk through Module 04. Each attendee creates a simple plugin. |
| 1:35-1:50 | Deploy a Contract | Demonstrate the contract conversion pipeline. Attendees deploy to Base Sepolia. |
| 1:50-2:00 | Wrap-Up and Next Steps | Point to the courses, the repository's issue tracker, and additional resources. Collect feedback. |

### Tips for Facilitators
- Test everything on the venue's WiFi before attendees arrive. Many workshop failures are network issues.
- Have a backup plan for installation problems. A pre-configured cloud environment eliminates local setup headaches.
- Keep the group together. If someone falls behind, pause and help them catch up. A workshop where half the room is stuck is not useful.
- Provide a feedback form at the end. Three questions are enough: What worked? What did not? Would you recommend this to a colleague?

## Certificates

No workshop or course completion certificate is issued. There is no certification portal, and nothing reviews submitted exercises or solutions.

The gateway does run three certification exams, developer, auditor and enterprise (`GET /certification/tracks` lists them). `POST /certification/start` begins one and `POST /certification/submit` scores the answers. A passing score records a certificate with an ID, which `GET /certification/{cert_id}` looks up. No on-chain attestation is written for a certificate yet.
