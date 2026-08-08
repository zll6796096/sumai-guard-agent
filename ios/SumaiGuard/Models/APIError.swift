import Foundation

enum APIError: Error, Equatable, Sendable {
    case invalidImage
    case appCheckInvalid
    case imageTooLarge
    case serviceLimited
    case geminiUnavailable
    case internalError
    case invalidResponse
    case network
    case cancelled
}

extension APIError {
    static func fromTransport(_ error: any Error) -> APIError {
        if error is CancellationError {
            return .cancelled
        }
        if let urlError = error as? URLError, urlError.code == .cancelled {
            return .cancelled
        }
        return .network
    }
}

struct ServerErrorEnvelope: Decodable, Equatable, Sendable {
    enum Code: String, Decodable, Equatable, Sendable {
        case invalidImage = "INVALID_IMAGE"
        case appCheckInvalid = "APP_CHECK_INVALID"
        case imageTooLarge = "IMAGE_TOO_LARGE"
        case serviceLimited = "SERVICE_LIMITED"
        case geminiUnavailable = "GEMINI_UNAVAILABLE"
        case internalError = "INTERNAL_ERROR"
    }

    let code: Code

    private enum CodingKeys: String, CodingKey {
        case code = "error"
        case message
    }

    init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        code = try container.decode(Code.self, forKey: .code)
        _ = try container.decode(String.self, forKey: .message)
    }

    static func map(statusCode: Int, body: Data) -> APIError {
        guard let envelope = try? JSONDecoder.sumai.decode(Self.self, from: body) else {
            return .invalidResponse
        }

        switch (statusCode, envelope.code) {
        case (400, .invalidImage):
            return .invalidImage
        case (401, .appCheckInvalid):
            return .appCheckInvalid
        case (413, .imageTooLarge):
            return .imageTooLarge
        case (429, .serviceLimited):
            return .serviceLimited
        case (503, .geminiUnavailable):
            return .geminiUnavailable
        case (500, .internalError):
            return .internalError
        default:
            return .invalidResponse
        }
    }
}
