# Module 05: Staking and Yield

## What Staking Is

Staking is the blockchain equivalent of a term deposit. You lock your tokens in a smart contract for a period of time, and in return, you earn rewards. During the lock period, you cannot spend or transfer those tokens.

Why would anyone pay you for locking tokens? Two main reasons:

1. **Network security**: On proof-of-stake blockchains, staked tokens help validate transactions and secure the network. Stakers are rewarded for this service because without them, the network would not function.

2. **Protocol incentives**: DeFi protocols pay staking rewards to attract liquidity. A lending protocol needs deposits to function. By offering rewards to depositors who stake (lock) their tokens, the protocol ensures it has enough liquidity to operate.

The reward for staking is expressed as **APY** (Annual Percentage Yield) -- the return you would earn over a full year, including the effect of compounding.

## How APY Is Calculated

APY is not a fixed promise. It is a snapshot of current conditions projected over a year.

If a staking pool is distributing 100 tokens per day in rewards, and the pool has 10,000 tokens staked, each staked token earns 0.01 tokens per day. Over 365 days, that is 3.65 tokens per staked token, or 365% APY (before compounding).

But here is the catch: as more people stake in the pool, the rewards are split among more participants. If the pool grows to 100,000 tokens, each token now earns only 0.001 per day, and the APY drops to 36.5%.

APY changes constantly based on:
- **Total staked**: More stakers means lower APY per person
- **Reward rate**: The protocol may change how many rewards it distributes
- **Token price**: If the reward token's price drops, the dollar-value APY drops even if the token-denominated APY stays the same

A pool advertising 200% APY today could be 20% APY next week if a large amount of capital enters. Always look at the trend, not just the current number.

## Risks of Staking

Staking is not risk-free. Three main risks:

### Slashing

On proof-of-stake networks, validators who misbehave (going offline, double-signing blocks, acting maliciously) have a portion of their staked tokens destroyed. This is called **slashing**. If you delegate your tokens to a validator and that validator gets slashed, you lose tokens too.

The purpose of slashing is to make attacks expensive. A validator who tries to manipulate the network risks losing their entire stake. This aligns incentives -- validators earn rewards for honest behavior and lose money for dishonest behavior.

To minimize slashing risk: choose established validators with high uptime records, diversify across multiple validators, and avoid validators offering suspiciously high commission rates (they may be cutting corners on infrastructure).

### Impermanent Loss

This risk applies specifically to **liquidity provider (LP) staking** in decentralized exchanges. When you provide liquidity to a trading pair (e.g., ETH/USDC), you deposit equal values of both tokens. The automated market maker uses your tokens to facilitate trades.

The problem: if the price ratio of the two tokens changes significantly, you end up with more of the cheaper token and less of the expensive one. When you withdraw, you may have less total value than if you had simply held the tokens.

It is called "impermanent" because if the prices return to their original ratio, the loss disappears. But if you withdraw while prices are diverged, the loss becomes permanent.

Example: You deposit $500 ETH + $500 USDC. ETH doubles in price. If you had just held, you would have $1,000 ETH + $500 USDC = $1,500. But as an LP, the pool rebalanced, and you might have $612 ETH + $612 USDC = $1,224. The $276 difference is impermanent loss.

The trading fees you earn as an LP may or may not offset this loss. High-volume pools with stable pairs tend to generate enough fees to compensate. Low-volume pools with volatile pairs often do not.

### Smart Contract Risk

Your staked tokens are held in a smart contract. If that contract has a bug, your tokens could be stolen or locked permanently. This is why the Glasswing audit covered in Course 02 matters -- it applies to staking contracts too.

Mitigation: stake in audited protocols, prefer protocols with track records, and never stake more than you can afford to lose.

## Using 0pnMatrx Staking Service

0pnMatrx provides a staking service accessible through Trinity:

```
You: What staking options are available right now?

Trinity: Here are the current staking opportunities on Base:
  
  1. ETH Staking
     APY: 4.2%  |  Lock period: None (liquid staking)
     Risk: Low  |  Min deposit: 0.01 ETH
  
  2. USDC Lending Pool
     APY: 6.8%  |  Lock period: None
     Risk: Low-Medium  |  Min deposit: 10 USDC
  
  3. ETH/USDC LP
     APY: 18.5%  |  Lock period: None
     Risk: Medium (impermanent loss)  |  Min deposit: $50 equivalent
```

To stake:

```
You: Stake 0.5 ETH in the liquid staking pool

Trinity: Staking 0.5 ETH in the liquid staking pool:
  - Current APY: 4.2%
  - Estimated annual reward: 0.021 ETH
  - Lock period: None (you can unstake anytime)
  - You will receive 0.5 stETH (liquid staking token)
  
  [Morpheus confirms the transaction]
```

The liquid staking token (stETH in this example) represents your staked position. You can hold it, use it as collateral for loans, or sell it. When you want to unstake, you redeem the stETH for ETH plus accumulated rewards.

## Comparing Yields Responsibly

When evaluating staking opportunities, look beyond the APY number:

1. **Sustainability**: Is the APY funded by protocol revenue or by token inflation? Revenue-funded yields are sustainable. Inflationary yields dilute the token and eventually collapse.

2. **Lock periods**: Higher APY often comes with longer lock periods. If you cannot withdraw for 90 days and the market crashes, you are stuck.

3. **Audit status**: Has the staking contract been audited? By whom? When? Was the audit performed on the currently deployed version?

4. **Track record**: How long has the protocol been running? Has it handled market stress without issues?

5. **Total value locked (TVL)**: How much value is in the protocol? Very low TVL may indicate risk. Very high TVL with low APY may indicate a mature, stable opportunity.

If an APY looks too good to be true, it probably is. Sustainable yields in DeFi range from 3-15% for established protocols. Anything above 50% should be examined very carefully. Anything above 1,000% is almost certainly unsustainable and likely involves significant token inflation or risk.

## Key Takeaways

- Staking locks tokens in exchange for rewards, measured as APY
- APY changes constantly based on total staked, reward rates, and prices
- Three main risks: slashing, impermanent loss, and smart contract bugs
- 0pnMatrx provides access to staking through Trinity
- Compare yields using sustainability, lock periods, audit status, and track record
- If the APY looks too good to be true, it almost certainly is

---

**Course complete.** You now understand the fundamentals of DeFi: lending, NFTs, DAOs, and staking. Start with testnets, use small amounts, and build your understanding through practice.
