# Module 02: Getting a DeFi Loan

## Overview

Getting a loan in DeFi is faster than getting a bank loan, but it carries different risks. This module walks through the entire process using 0pnMatrx, from depositing collateral to repaying the loan.

## Step 1: Using 0pnMatrx to Borrow

Instead of navigating a DeFi protocol's website, connecting a wallet, and approving multiple transactions, you chat with Trinity:

```
You: I want to borrow 500 USDC using ETH as collateral. What do I need to deposit?

Trinity: To borrow 500 USDC, you need to deposit ETH as collateral. 
The current collateral ratio requirement is 150%, which means you 
need to deposit at least $750 worth of ETH.

At the current ETH price of $2,500, that's 0.3 ETH minimum. 
I recommend depositing at least 0.4 ETH ($1,000) to give yourself 
a safety margin against price drops.

Would you like to proceed with 0.4 ETH as collateral to borrow 500 USDC?
```

Trinity calculates the requirements, checks current prices, and recommends a safe deposit amount. Morpheus will appear for confirmation before the actual deposit, since depositing collateral and taking a loan are financial operations that commit real assets.

## Step 2: Understanding Collateral Ratios

The **collateral ratio** is the relationship between your collateral's value and your loan. A 150% collateral ratio means your collateral must be worth at least 1.5 times your loan.

| Your Collateral | Your Loan | Collateral Ratio | Status |
|----------------|-----------|-------------------|--------|
| $1,000 in ETH | $500 USDC | 200% | Safe |
| $750 in ETH | $500 USDC | 150% | Minimum |
| $600 in ETH | $500 USDC | 120% | Liquidation risk |

**Liquidation threshold** is typically around 120-130%. If your collateral ratio drops below this, the protocol begins liquidating your position.

Why not just require exactly 100%? Because crypto prices are volatile. The buffer protects lenders. If ETH drops 20% in an hour, a 100% collateral ratio would mean the loan is instantly underwater. The buffer gives the protocol time to liquidate before losses exceed the collateral.

## Step 3: Managing Your Position

After taking a loan, your main job is monitoring your collateral ratio. You can check it anytime:

```
You: What's my current loan position?

Trinity: Your active loan position:
  Collateral: 0.4 ETH ($980 at current price)
  Borrowed: 500 USDC
  Collateral Ratio: 196%
  Liquidation Price: $1,562.50 per ETH
  Interest Accrued: 1.23 USDC (0.25% since opening)
  
  Your position is healthy. ETH would need to drop 37% 
  from the current price to trigger liquidation.
```

Key numbers to watch:

- **Collateral Ratio**: Above 150% is comfortable. Below 130% is dangerous.
- **Liquidation Price**: The ETH price at which your position gets liquidated. If the current price approaches this, take action.
- **Interest Accrued**: The amount of additional USDC you owe beyond the original loan.

If your collateral ratio drops too low, you have two options:

1. **Add more collateral**: Deposit additional ETH to increase the ratio
2. **Repay some of the loan**: Pay back part of the USDC to reduce the borrowed amount

```
You: Add 0.1 ETH to my collateral

Trinity: Adding 0.1 ETH to your position...
  [Morpheus confirms the transaction]
  
  Updated position:
  Collateral: 0.5 ETH ($1,225 at current price)
  Borrowed: 500 USDC
  Collateral Ratio: 245%
```

## Step 4: Repaying and Withdrawing

When you are ready to close your position:

```
You: I want to repay my loan and get my ETH back

Trinity: Your total repayment amount:
  Original loan: 500.00 USDC
  Accrued interest: 3.47 USDC
  Total due: 503.47 USDC
  
  After repayment, your 0.5 ETH collateral will be 
  returned to your wallet. Shall I proceed?
```

After repaying, Morpheus confirms the transaction, the USDC is returned to the lending pool, and your ETH collateral is released back to your wallet.

You can also make partial repayments. Paying back 250 USDC would reduce your loan to approximately 253 USDC (plus remaining interest), lowering your risk while keeping the position open.

## Step 5: What Happens if You Get Liquidated

If your collateral ratio drops below the liquidation threshold, the protocol does not call you or send a warning email. It acts immediately.

Here is what happens:

1. **Detection**: A "liquidator" (a bot or user monitoring the protocol) notices your position is below the threshold
2. **Liquidation call**: The liquidator calls the liquidation function on the smart contract
3. **Collateral sale**: The protocol sells enough of your collateral to repay your loan
4. **Penalty applied**: You lose an additional 5-15% of your collateral as a liquidation penalty (this rewards the liquidator for their service)
5. **Remainder returned**: If any collateral remains after repaying the loan and penalty, it is returned to your wallet

**Example**: You deposited $1,000 in ETH, borrowed $500 USDC. ETH drops 45%.

- Collateral now worth: $550
- Loan amount: $500 (plus interest)
- Liquidation: $500 sold to repay loan, ~$25 penalty to liquidator
- Returned to you: ~$25 (instead of your original $1,000 in ETH)

The lesson is clear: **never borrow the maximum**. Always maintain a comfortable buffer. Market crashes happen faster than you can react.

## Practical Tips

1. **Start small**: Your first loan should be a small amount you are comfortable losing entirely
2. **Use testnets**: Practice on Base Sepolia before using real money
3. **Set alerts**: Ask Trinity to notify you if your collateral ratio drops below 170%
4. **Do not borrow the maximum**: A 200%+ collateral ratio gives you room to breathe
5. **Understand the interest**: DeFi interest rates fluctuate. A 3% rate today could be 15% next week during high demand

## Key Takeaways

- DeFi loans require collateral, not credit scores
- The collateral ratio must stay above the liquidation threshold (typically 120-130%)
- Monitor your position regularly; liquidation happens automatically with no warning
- You can add collateral or repay partially to manage risk
- Always start on testnet and with amounts you can afford to lose

---

**Next:** [NFT Royalties](./03-nft-royalties.md) -- understand what NFTs really are and how royalties work on-chain.
