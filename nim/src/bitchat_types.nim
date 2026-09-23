type
  MessageType* {.size: sizeof(uint8).} = enum
    Announce = 0x01
    KeyExchange = 0x02
    Leave = 0x03
    Message = 0x04
    FragmentStart = 0x05
    FragmentContinue = 0x06
    FragmentEnd = 0x07
    ChannelAnnounce = 0x08
    ChannelRetention = 0x09
    DeliveryAck = 0x0A
    DeliveryStatusRequest = 0x0B
    ReadReceipt = 0x0C
    NoiseHandshakeInit = 0x10
    NoiseHandshakeResp = 0x11
    NoiseEncrypted = 0x12
    NoiseIdentityAnnounce = 0x13
    VersionHello = 0x20
    VersionAck = 0x21
    ProtocolAck = 0x22
    ProtocolNack = 0x23
    SystemValidation = 0x24
    HandshakeRequest = 0x25

const
  CurrentProtocolVersion*: uint8 = 1
  FixedHeaderSize*: int = 14
  MinimumPacketSize*: int = 22
  SenderIdSize*: int = 8
  RecipientIdSize*: int = 8
  SignatureSize*: int = 64
  MaxPaddingSize*: int = 255
  PaddingOverheadEstimate*: int = 16

  FlagHasRecipient*: uint8 = 0x01
  FlagHasSignature*: uint8 = 0x02
  FlagIsCompressed*: uint8 = 0x04

  BlockSizes*: array[4, int] = [256, 512, 1024, 2048]

  FragmentationThreshold*: int = 500
  FragmentChunkSize*: int = 150
  FragmentHeaderSize*: int = 13
  FragmentIdSize*: int = 8

  MaxFragmentsPerAssembly*: int = 1000
  MaxActiveAssemblies*: int = 100
  MaxReassembledBytes*: int = 150_000

  BitchatOk*: int32 = 0
  ErrBufferTooSmall*: int32 = -1
  ErrInvalidInput*: int32 = -2
  ErrPacketTooSmall*: int32 = -3
  ErrBadVersion*: int32 = -4
  ErrBadMsgType*: int32 = -5
  ErrCorruptPadding*: int32 = -6
  ErrFragmentLimit*: int32 = -7
  ErrConflictingFragment*: int32 = -8
  ErrNotFound*: int32 = -9

proc isValidMessageType*(val: uint8): bool =
  case val
  of 0x01..0x0C, 0x10..0x13, 0x20..0x25:
    result = true
  else:
    result = false
