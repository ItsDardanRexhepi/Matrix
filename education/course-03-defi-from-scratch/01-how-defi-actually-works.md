# Module 01: How DeFi Actually Works

## What DeFi Is

DeFi stands for Decentralized Finance. Strip away the jargon and it means one thing: financial services without banks.

When you get a loan from a bank, a human reviews your application, checks your credit score, and decides whether to approve it. When you earn interest on a savings account, the bank sets the rate and can change it whenever they want. When you trade stocks, a broker executes the trade on an exchange with business hours.

DeFi replaces all of those humans and institutions with smart contracts -- programs that run on a blockchain, execute the same rules for everyone, and are available 24/7. No credit checks, no business hours, no applications. Just code that does exactly what it says it will do.

## The Building Blocks

DeFi is built on a few core concepts. Once you understand these, every DeFi protocol is a variation on the same themes.

### Collateral (Like a Pawn Shop, But Automated)

A traditional pawn shop works like this: you bring in a watch worth $500, the shop gives you $300 in cash (a loan), and if you pay back $300 plus interest, you get your watch back. If you do not pay, they keep the watch and sell it.

DeFi lending works the same way, but the pawn shop is a smart contract. Instead of a watch, you deposit cryptocurrency (collateral). Instead of a human deciding how much to lend you, the contract uses a formula. Typically, you can borrow 50-80% of your collateral's value. If you deposited $1,000 worth of ETH, you might be able to borrow up to $750 in stablecoins (crypto tokens pegged to the US dollar).

The entire process is automatic. No one decides whether to approve you. If you have the collateral, you get the loan.

### Liquidation (When Collateral Drops)

Here is where it gets important. Cryptocurrency prices change constantly. If you deposited $1,000 worth of ETH as collateral and borrowed $750, what happens if ETH drops 30% and your collateral is now worth only $700?

Your collateral no longer covers your loan. The smart contract detects this and begins **liquidation** -- it sells your collateral to repay the loan. This happens automatically, without warning, and typically with a liquidation penalty (you lose an extra 5-15% on top of the loss). The protocol needs to protect its lenders, so it acts fast.

This is the single most important risk in DeFi lending. When you borrow, you are betting that your collateral will not drop too much in value. If it does, you lose it.

### Interest Rates (How They Work On-Chain)

In traditional finance, a committee at a bank decides interest rates. In DeFi, interest rates are calculated by a formula based on supply and demand.

The concept is called a **utilization rate**. If a lending pool has $10 million deposited and $2 million borrowed, utilization is 20%. At low utilization, interest rates are low (lots of supply, not much demand). As utilization increases, rates increase to attract more depositors and discourage excessive borrowing.

This happens in real time, block by block. Your interest rate can change every 12 seconds (the time between blocks on Ethereum). In practice, rates change gradually because utilization changes gradually, but during market volatility, rates can spike.

The interest goes to the people who deposited assets into the pool. This is how you earn yield in DeFi -- by depositing assets that others borrow. The protocol takes a small cut (typically 10-20%), and the rest goes to depositors.

### Stablecoins (The Bridge to Real Value)

Most DeFi activity uses **stablecoins** -- tokens designed to maintain a 1:1 peg with the US dollar. The most common are USDC (backed by cash reserves at regulated institutions) and DAI (backed by crypto collateral locked in smart contracts).

Stablecoins are the bridge between volatile crypto prices and predictable dollar values. When you borrow in DeFi, you typically borrow stablecoins. When you compare interest rates, they are quoted in stablecoin terms.

## The Services

0pnMatrx provides 30 blockchain services, many of which are DeFi services. Here are the main categories:

**Lending and Borrowing**: Deposit collateral, borrow stablecoins, earn interest on deposits.

**Token Swaps**: Trade one token for another directly, without an exchange. This uses Automated Market Makers (AMMs) -- pools of tokens that use a mathematical formula to determine exchange rates.

**Staking**: Lock tokens to earn rewards. This secures the network and earns you a return, similar to earning interest.

**NFTs**: Non-fungible tokens representing unique ownership. Used for art, but also for real-world assets, tickets, memberships, and royalties.

**DAOs**: Decentralized Autonomous Organizations. Groups that make collective decisions through voting, governed by smart contracts.

## Why This Matters for Regular People

Three billion people worldwide do not have access to basic financial services. They cannot get a bank account, a loan, or insurance. DeFi does not care about your country, your credit score, or your social status. It cares about one thing: do you have collateral?

That is both its strength and its limitation. DeFi is not a replacement for all banking -- it is an alternative for people who either cannot access or choose not to use traditional finance. It is also a laboratory for new financial tools that may eventually be adopted by mainstream institutions.

0pnMatrx makes DeFi accessible by removing the technical barrier. Instead of connecting wallets, approving transactions, and navigating complex interfaces, you have a conversation with Trinity. The technical complexity is handled; the financial decisions are still yours.

## Key Takeaways

- DeFi replaces banks with smart contracts: loans, interest, trading, all automated
- Collateral is the foundation: you deposit assets to borrow against
- Liquidation is the main risk: if collateral drops too much, you lose it
- Interest rates are set by supply and demand, updating in real time
- 0pnMatrx provides access to DeFi through natural conversation

---

**Next:** [Getting a DeFi Loan](./02-getting-a-defi-loan.md) -- walk through the process step by step.
