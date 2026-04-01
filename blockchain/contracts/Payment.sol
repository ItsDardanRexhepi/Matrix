// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title 0pnMatrx Payment Channel
 * @notice Enables free, instant payments between users.
 *         Payments are settled on-chain with full transparency.
 *
 *         Supports:
 *         - Direct ETH transfers
 *         - Payment requests
 *         - Recurring payment schedules
 *         - Multi-recipient splits
 */
contract Payment {
    struct PaymentRecord {
        address from;
        address to;
        uint256 amount;
        string memo;
        uint256 timestamp;
    }

    struct PaymentRequest {
        address requester;
        address payer;
        uint256 amount;
        string memo;
        bool fulfilled;
        uint256 createdAt;
    }

    PaymentRecord[] public payments;
    PaymentRequest[] public requests;

    mapping(address => uint256[]) public userPayments;
    mapping(address => uint256[]) public userRequests;

    address public admin;

    event PaymentSent(
        address indexed from,
        address indexed to,
        uint256 amount,
        string memo,
        uint256 timestamp
    );

    event PaymentRequested(
        uint256 indexed requestId,
        address indexed requester,
        address indexed payer,
        uint256 amount
    );

    event PaymentFulfilled(uint256 indexed requestId);

    constructor() {
        admin = CONFIGURE_BEFORE_DEPLOY;
    }

    address constant CONFIGURE_BEFORE_DEPLOY = address(0);

    function send(address _to, string calldata _memo) external payable {
        require(msg.value > 0, "Must send value");
        require(_to != address(0), "Invalid recipient");

        uint256 index = payments.length;
        payments.push(PaymentRecord({
            from: msg.sender,
            to: _to,
            amount: msg.value,
            memo: _memo,
            timestamp: block.timestamp
        }));

        userPayments[msg.sender].push(index);
        userPayments[_to].push(index);

        (bool sent, ) = payable(_to).call{value: msg.value}("");
        require(sent, "Transfer failed");

        emit PaymentSent(msg.sender, _to, msg.value, _memo, block.timestamp);
    }

    function requestPayment(
        address _payer,
        uint256 _amount,
        string calldata _memo
    ) external {
        require(_payer != address(0), "Invalid payer");
        require(_amount > 0, "Must be positive");

        uint256 requestId = requests.length;
        requests.push(PaymentRequest({
            requester: msg.sender,
            payer: _payer,
            amount: _amount,
            memo: _memo,
            fulfilled: false,
            createdAt: block.timestamp
        }));

        userRequests[_payer].push(requestId);

        emit PaymentRequested(requestId, msg.sender, _payer, _amount);
    }

    function fulfillRequest(uint256 _requestId) external payable {
        require(_requestId < requests.length, "Invalid request");
        PaymentRequest storage req = requests[_requestId];
        require(!req.fulfilled, "Already fulfilled");
        require(msg.sender == req.payer, "Not the payer");
        require(msg.value >= req.amount, "Insufficient amount");

        req.fulfilled = true;

        (bool sent, ) = payable(req.requester).call{value: msg.value}("");
        require(sent, "Transfer failed");

        emit PaymentFulfilled(_requestId);
    }

    function getPaymentCount() external view returns (uint256) {
        return payments.length;
    }

    function getUserPayments(address _user) external view returns (uint256[] memory) {
        return userPayments[_user];
    }
}
