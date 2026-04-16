# Community Guide

## Discord Server Structure

The 0pnMatrx community Discord is organized into channels that match the topics people need help with:

### Public Channels
- **#general** -- Open discussion about 0pnMatrx, blockchain, and AI. Introductions welcome. Keep it constructive.
- **#announcements** -- Official updates from the core team. Read-only for members.
- **#showcase** -- Share what you have built with 0pnMatrx. Deployed contracts, plugins, integrations, projects in progress. This is the place to get feedback and recognition.

### Course Channels (accessible after purchase)
- **#course-help** -- General questions about course content, exercises, and setup issues. If your question is specific to a course topic, use the dedicated channel below.
- **#plugin-dev** -- Discussion about plugin development, the OpenMatrixPlugin interface, marketplace submissions, and integration patterns.
- **#smart-contract-security** -- Security questions, vulnerability analysis, Glasswing audit results, and contract review requests.
- **#defi-questions** -- DeFi concepts, lending mechanics, staking strategies, and risk assessment.

### Moderation
- Be respectful. Technical disagreements are fine; personal attacks are not.
- No financial advice. Sharing knowledge about how DeFi works is encouraged. Telling someone to buy a specific token is not allowed.
- No spam or self-promotion outside #showcase.
- Use threads for multi-message conversations to keep channels readable.

## Weekly Office Hours

### Format
- **Duration**: 1 hour
- **Frequency**: Weekly (day and time announced in #announcements)
- **Platform**: Discord voice channel with screen sharing
- **Recording**: Sessions are recorded and posted in the relevant course channel for those who cannot attend live

### Structure
- **0:00-0:05** -- Welcome and topic overview
- **0:05-0:25** -- Prepared walkthrough of a common question or concept from that week
- **0:25-0:55** -- Open Q&A. Attendees can screen share their own code for live debugging and guidance
- **0:55-1:00** -- Wrap-up and preview of next week's topic

### How to Get the Most Out of Office Hours
- Come with specific questions. "My plugin doesn't load" is better than "plugins are confusing."
- If you want to screen share, have your environment ready before the session starts.
- Review the recording if you missed it. Most recurring questions are answered in past sessions.
- If your question is not answered during the session, post it in the relevant Discord channel afterward.

## How to Run a Workshop

Community members are encouraged to run workshops for their teams, meetup groups, or local communities. Here is a template for a 2-hour workshop.

### Workshop Template Agenda

**Title**: Introduction to 0pnMatrx -- Hands-On Workshop

**Duration**: 2 hours

**Prerequisites for Attendees**: Laptop with Python 3.11+ installed, internet connection, text editor

**Facilitator Prep**: Clone the repo, run setup.py, verify the gateway starts on your machine before the workshop.

| Time | Activity | Description |
|------|----------|-------------|
| 0:00-0:10 | Welcome and Setup | Verify all attendees have Python and git. Help with any installation issues. |
| 0:10-0:25 | What is 0pnMatrx? | Present Module 01 content. Cover the three agents, the architecture, and the 221-capability catalog organized by category. |
| 0:25-0:45 | Live Setup | Everyone clones the repo, runs setup, and starts the gateway. Troubleshoot together. |
| 0:45-1:00 | First Interaction | Attendees send their first /chat request via curl. Discuss the response format. |
| 1:00-1:10 | Break | |
| 1:10-1:35 | Build a Plugin | Walk through Module 04. Each attendee creates a simple plugin. |
| 1:35-1:50 | Deploy a Contract | Demonstrate the contract conversion pipeline. Attendees deploy to Base Sepolia. |
| 1:50-2:00 | Wrap-Up and Next Steps | Point to courses, Discord, and additional resources. Collect feedback. |

### Tips for Facilitators
- Test everything on the venue's WiFi before attendees arrive. Many workshop failures are network issues.
- Have a backup plan for installation problems. A pre-configured cloud environment eliminates local setup headaches.
- Keep the group together. If someone falls behind, pause and help them catch up. A workshop where half the room is stuck is not useful.
- Provide a feedback form at the end. Three questions are enough: What worked? What did not? Would you recommend this to a colleague?

## How to Certify Workshop Completion

Attendees who complete all workshop exercises can receive a **0pnMatrx Workshop Completion Certificate**.

### Certification Process

1. **Complete exercises**: The attendee must demonstrate a working plugin, a successful /chat interaction, and a deployed testnet contract.
2. **Facilitator verification**: The workshop facilitator reviews each attendee's work during or after the workshop.
3. **Submit for certification**: The facilitator submits the list of completed attendees through the certification portal.
4. **Certificate issued**: Each attendee receives a digital certificate with:
   - Their name
   - Workshop title and date
   - Facilitator name
   - Verification link (on-chain attestation via EAS)

The on-chain attestation ensures certificates cannot be forged. Anyone can verify a certificate by checking the attestation UID on the Base block explorer.

### For Course Completion Certification

Students who complete all exercises in a purchased course can apply for course completion certification:

1. Complete all exercises in the course
2. Submit your solutions through the certification portal
3. Solutions are reviewed against expected outputs
4. Upon approval, a certificate is issued with an EAS attestation

Course completion certificates carry more weight than workshop certificates because they cover more material and are individually reviewed.
