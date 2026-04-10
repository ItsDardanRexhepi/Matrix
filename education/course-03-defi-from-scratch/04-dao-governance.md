# Module 04: DAO Governance

## What a DAO Is

A DAO (Decentralized Autonomous Organization) is a company run by code and votes instead of executives and boards.

In a traditional company, the CEO decides strategy, the CFO controls the budget, and the board approves major decisions. Employees follow directives from above. If the CEO makes a bad decision, employees can complain, but the CEO still has the authority to act.

In a DAO, there is no CEO. Decisions are made through proposals and votes. The rules for voting, the threshold for passing, and the execution of approved proposals are all encoded in smart contracts. No single person can override a vote or spend treasury funds without approval.

Think of it like this: a traditional company is a monarchy. A DAO is a direct democracy.

## Creating a DAO on 0pnMatrx

Setting up a DAO through 0pnMatrx is a conversation with Trinity:

```
You: Create a DAO called "BuilderDAO" for our development community. 
     We want token-based voting with a 1-week voting period and 
     a 51% approval threshold to pass proposals.

Trinity: I'll set up BuilderDAO with these parameters:
  - Name: BuilderDAO
  - Governance token: BLDAO (I'll create this ERC-20 token)
  - Voting period: 7 days
  - Quorum: 10% of total supply must participate
  - Approval threshold: 51% of votes must be in favor
  - Timelock: 48-hour delay between approval and execution
  
  [Morpheus confirms the deployment]
  
  BuilderDAO is live.
  Governance contract: 0x...
  Token contract: 0x...
  Timelock contract: 0x...
```

Three contracts are deployed: the governance token (voting power), the governor contract (proposal and voting logic), and the timelock (delay between approval and execution).

## Proposals, Voting, and Execution

### Creating a Proposal

Any token holder can create a proposal. A proposal describes what should happen and includes the actual transaction data that will execute if approved.

```
You: Create a proposal in BuilderDAO to allocate 10,000 USDC 
     from the treasury to fund a developer bounty program.

Trinity: I'll create a proposal with the following:
  Title: Fund Developer Bounty Program
  Description: Allocate 10,000 USDC from the BuilderDAO treasury 
    to fund community developer bounties for Q3 2026.
  Action: Transfer 10,000 USDC from treasury to bounty multisig
  
  Voting starts immediately and runs for 7 days.
  Proposal ID: 42
```

### Voting

Token holders vote with their tokens. Each token equals one vote. You can vote For, Against, or Abstain.

```
You: Vote in favor of proposal 42 in BuilderDAO

Trinity: Vote recorded:
  Proposal: #42 - Fund Developer Bounty Program
  Your vote: For
  Your voting power: 5,000 BLDAO tokens
  Current tally: 23,000 For / 8,000 Against / 2,000 Abstain
  Time remaining: 5 days, 12 hours
```

Voting power is typically based on a snapshot -- the number of tokens you held at a specific block, not the current block. This prevents someone from buying tokens right before a vote, voting, and selling immediately.

### Execution

If a proposal passes (meets both quorum and approval threshold), it enters the timelock period. After the timelock expires, anyone can call the execute function to carry out the approved transaction.

```
You: Execute proposal 42 in BuilderDAO

Trinity: Proposal #42 has passed and the timelock has expired.
  Executing: Transfer 10,000 USDC to bounty multisig
  
  [Morpheus confirms the transaction]
  
  Executed successfully. 
  10,000 USDC transferred from treasury to 0x...
  Transaction: 0x...
```

The execution is the actual on-chain transaction. It runs exactly the code that was proposed -- not an approximation, not an interpretation. This is why the timelock exists: it gives members time to review the exact transaction before it executes.

## Treasury Management

A DAO's treasury is its bank account. It holds funds contributed by members, earned through protocol fees, or received through grants. The treasury is controlled by the governance contracts -- no individual can spend funds without a passed proposal.

Common treasury operations:
- **Funding initiatives**: Allocating funds for development, marketing, or bounties
- **Paying contributors**: Regular payments to people who work for the DAO
- **Investing**: Moving treasury assets into yield-generating positions
- **Token buybacks**: Purchasing the DAO's own governance token from the market

All of these require a proposal, vote, and execution. This makes treasury operations transparent -- every expenditure is recorded on-chain and requires community approval.

## Real-World DAO Examples

**MakerDAO**: Governs the DAI stablecoin. Token holders vote on risk parameters, collateral types, and interest rates. Treasury manages billions of dollars in assets.

**Uniswap DAO**: Governs the largest decentralized exchange. Votes on fee structures, liquidity incentives, and protocol upgrades.

**ENS DAO**: Manages the Ethereum Name Service (blockchain domain names). Decides on pricing, registration rules, and treasury allocation.

These DAOs demonstrate that the model works for managing real organizations with real money. They also demonstrate the challenges: voter apathy (low participation), whale dominance (large token holders controlling outcomes), and governance attacks (temporarily acquiring tokens to push malicious proposals).

## Limitations and Tradeoffs

DAOs are not perfect. Some honest tradeoffs:

- **Speed**: A 7-day voting period means urgent decisions take at least a week. Traditional companies can act in hours.
- **Voter apathy**: Most token holders do not vote. Participation rates of 5-15% are common. This means a small minority of active voters make decisions for everyone.
- **Complexity**: Participating in governance requires reading proposals, understanding technical implications, and spending gas to vote. Many token holders do not have the time or expertise.
- **Plutocracy risk**: One token equals one vote means wealthy participants have more influence. This mirrors shareholder voting in traditional companies.

Despite these challenges, DAOs represent a meaningful experiment in organizational governance. They provide transparency, accountability, and permissionless participation that traditional structures cannot match.

## Key Takeaways

- DAOs replace executives with proposals, votes, and smart contract execution
- Token holders vote on proposals; approved proposals execute automatically after a timelock
- Treasury management is fully transparent and requires community approval
- Real-world DAOs govern billions of dollars in assets
- Tradeoffs include speed, voter apathy, and plutocracy risk

---

**Next:** [Staking and Yield](./05-staking-and-yield.md) -- learn how locking tokens earns rewards and what risks to watch for.
