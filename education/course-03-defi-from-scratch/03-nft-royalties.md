# Module 03: NFT Royalties

## What NFTs Actually Are

Forget the hype about million-dollar monkey pictures. At its core, an NFT (Non-Fungible Token) is a certificate of ownership recorded on a blockchain.

**Fungible** means interchangeable. One dollar bill is the same as any other dollar bill. One Bitcoin is the same as any other Bitcoin. They are fungible.

**Non-fungible** means unique. Your house is non-fungible -- there is only one house at your address. A concert ticket for Seat 42, Row G is non-fungible -- no other ticket gives you that specific seat.

An NFT is a unique token on the blockchain that represents ownership of something. That something can be digital art, but it can also be:

- A deed to real property
- A membership pass to a community
- A license to use software
- A ticket to an event
- A certificate of authenticity for a physical item
- A music royalty share

The NFT itself is not the image or the music. The NFT is the proof that you own it. It is recorded on a public blockchain, so anyone can verify ownership without calling a central authority.

## How Royalties Work On-Chain

In the traditional art world, an artist sells a painting once and gets paid once. If that painting resells for 10 times the price at auction, the artist gets nothing.

NFT royalties change this. The smart contract that creates an NFT can include an automatic royalty -- a percentage of every future sale that goes back to the original creator. If an artist sets a 5% royalty and their NFT resells for $10,000, the artist automatically receives $500.

The standard for on-chain royalties is **EIP-2981**, which defines a simple interface:

```
function royaltyInfo(uint256 tokenId, uint256 salePrice) 
    returns (address receiver, uint256 royaltyAmount)
```

When a marketplace sells an NFT, it calls this function to determine how much royalty to pay and to whom. The function returns the royalty receiver's address and the amount owed.

**Important distinction**: EIP-2981 tells marketplaces what the royalty should be, but it does not enforce payment. Whether the royalty is actually paid depends on the marketplace's implementation. This leads to the enforcement problem discussed below.

## Creating an NFT with Automatic Royalties on 0pnMatrx

Through 0pnMatrx, creating an NFT with royalties is a conversation:

```
You: Create an NFT collection called "Cityscapes" with a 7.5% 
     royalty on all secondary sales. I want to mint 100 editions 
     of my first piece.

Trinity: I'll create a Cityscapes NFT collection with these parameters:
  - Collection name: Cityscapes
  - Standard: ERC-721 with EIP-2981 royalties
  - Royalty: 7.5% on all secondary sales, paid to your wallet
  - First mint: 100 editions
  
  [Morpheus confirms the deployment]
  
  Collection deployed. Your first 100 NFTs have been minted.
  Contract address: 0x...
  Royalty receiver: 0x... (your wallet)
```

Behind the scenes, Neo deploys an ERC-721 contract with EIP-2981 implemented. The royalty percentage and receiver address are set in the contract and apply to every token in the collection. Each time one of your NFTs is resold on a marketplace that respects EIP-2981, 7.5% of the sale price is sent to your wallet automatically.

## Why On-Chain Enforcement Matters

Here is the uncomfortable truth about NFT royalties: most marketplaces made them optional.

When NFT marketplaces competed for users in 2022-2023, some eliminated royalty enforcement to attract sellers with lower fees. If a marketplace does not call `royaltyInfo()` or ignores the result, the creator gets nothing.

This matters because it changes the economics of being a creator. If royalties are optional, they are effectively voluntary tips. If they are enforced on-chain, they are guaranteed income.

**On-chain enforcement** means the royalty is built into the transfer function of the NFT itself. The NFT cannot be transferred unless the royalty is paid. This is technically possible through operator filtering and transfer hooks, though it comes with tradeoffs (it can limit where the NFT can be traded).

0pnMatrx supports on-chain royalty enforcement through its NFT creation service. When you create an NFT collection, you can choose between:

1. **Standard royalties (EIP-2981)**: Marketplaces are informed of the royalty but enforcement is up to them. Maximum compatibility.
2. **Enforced royalties**: The transfer function checks for royalty payment. The NFT can only be traded through compliant marketplaces. Guaranteed creator income but reduced marketplace compatibility.

The choice depends on your priorities: maximum reach or guaranteed royalties.

## Practical Considerations

**Royalty percentages**: The standard range is 2.5% to 10%. Higher royalties discourage secondary market trading because they increase the buyer's effective price. Lower royalties maximize trading volume but earn less per sale.

**Royalty recipients**: You can set the royalty to go to a single wallet, a multisig, a DAO treasury, or a splitter contract that divides payments among multiple creators.

**Metadata**: The NFT's metadata (name, description, image URI) is typically stored off-chain (on IPFS or Arweave) and referenced by the token. The NFT contract stores a pointer to the metadata, not the metadata itself. Make sure your metadata storage is permanent -- if the server hosting your metadata goes down, the NFT still exists but its content becomes inaccessible.

## Key Takeaways

- NFTs are ownership certificates on a blockchain, not just images
- EIP-2981 defines how royalties should work, but enforcement is marketplace-dependent
- On-chain enforcement guarantees royalties but limits marketplace compatibility
- 0pnMatrx lets you create NFT collections with royalties through conversation
- Royalty percentages between 2.5% and 10% are standard
- Metadata storage must be permanent (IPFS, Arweave) or it can disappear

---

**Next:** [DAO Governance](./04-dao-governance.md) -- learn how groups make decisions without a CEO.
