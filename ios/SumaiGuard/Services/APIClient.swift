import Foundation

protocol AppCheckTokenProviding: Sendable {
    func token() async throws -> String
}

protocol Analyzing: Sendable {
    func analyze(image: SanitizedImage, roomHint: String) async throws -> AnalysisResponse
}

enum APIOriginError: Error, Equatable, Sendable {
    case invalid
}

struct APIOrigin: Equatable, Sendable {
    let url: URL

    var analysisEndpoint: URL {
        url.appending(path: "api/v1/analyze", directoryHint: .notDirectory)
    }

    init(_ rawValue: String) throws {
        guard
            rawValue == rawValue.trimmingCharacters(in: .whitespacesAndNewlines),
            !rawValue.contains("%"),
            let components = URLComponents(string: rawValue),
            components.scheme?.lowercased() == "https",
            components.user == nil,
            components.password == nil,
            components.query == nil,
            components.fragment == nil,
            components.percentEncodedPath.isEmpty,
            components.port == nil,
            let originalHost = components.host,
            Self.isValidDNSHost(originalHost)
        else {
            throw APIOriginError.invalid
        }

        let host = originalHost.lowercased()
        var normalized = URLComponents()
        normalized.scheme = "https"
        normalized.host = host
        guard let url = normalized.url else {
            throw APIOriginError.invalid
        }
        self.url = url
    }

    private static func isValidDNSHost(_ value: String) -> Bool {
        let host = value.lowercased()
        guard
            !host.hasSuffix("."),
            host != "localhost",
            !host.hasSuffix(".localhost"),
            host.utf8.count <= 253,
            host.unicodeScalars.allSatisfy(\.isASCII)
        else {
            return false
        }

        let labels = host.split(separator: ".", omittingEmptySubsequences: false)
        guard labels.count >= 2 else {
            return false
        }
        if isLegacyNumericAddress(labels) {
            return false
        }

        return labels.allSatisfy { label in
            guard
                !label.isEmpty,
                label.utf8.count <= 63,
                label.first != "-",
                label.last != "-"
            else {
                return false
            }
            return label.unicodeScalars.allSatisfy { scalar in
                scalar.properties.isAlphabetic || scalar.properties.numericType != nil || scalar == "-"
            }
        }
    }

    private static func isLegacyNumericAddress(_ labels: [Substring]) -> Bool {
        guard (1...4).contains(labels.count) else {
            return false
        }
        return labels.allSatisfy(isLegacyNumericComponent)
    }

    private static func isLegacyNumericComponent(_ label: Substring) -> Bool {
        guard !label.isEmpty else {
            return false
        }

        if label.hasPrefix("0x") || label.hasPrefix("0X") {
            let digits = label.dropFirst(2)
            return !digits.isEmpty && digits.unicodeScalars.allSatisfy { scalar in
                switch scalar.value {
                case 48...57, 65...70, 97...102:
                    true
                default:
                    false
                }
            }
        }

        return label.unicodeScalars.allSatisfy { scalar in
            (48...57).contains(scalar.value)
        }
    }
}

final class APIClient: Analyzing, @unchecked Sendable {
    static let defaultMaximumResponseBytes = 10 * 1_024 * 1_024

    private let origin: APIOrigin
    private let tokenProvider: any AppCheckTokenProviding
    private let protocolClasses: [AnyClass]?
    private let maximumResponseBytes: Int

    init(
        origin: APIOrigin,
        tokenProvider: any AppCheckTokenProviding,
        protocolClasses: [AnyClass]? = nil,
        maximumResponseBytes: Int = APIClient.defaultMaximumResponseBytes
    ) {
        precondition(maximumResponseBytes > 0)
        self.origin = origin
        self.tokenProvider = tokenProvider
        self.protocolClasses = protocolClasses
        self.maximumResponseBytes = maximumResponseBytes
    }

    static func makeSessionConfiguration(
        protocolClasses: [AnyClass]? = nil
    ) -> URLSessionConfiguration {
        let configuration = URLSessionConfiguration.ephemeral
        configuration.urlCache = nil
        configuration.requestCachePolicy = .reloadIgnoringLocalCacheData
        configuration.timeoutIntervalForRequest = 120
        configuration.httpCookieStorage = nil
        configuration.httpShouldSetCookies = false
        configuration.urlCredentialStorage = nil
        if let protocolClasses {
            configuration.protocolClasses = protocolClasses
        }
        return configuration
    }

    func analyze(image: SanitizedImage, roomHint _: String) async throws -> AnalysisResponse {
        try Task.checkCancellation()

        var appCheckToken: String?
        do {
            appCheckToken = try await tokenProvider.token()
        } catch is CancellationError {
            throw CancellationError()
        } catch {
            throw APIError.appCheckInvalid
        }
        try Task.checkCancellation()

        guard appCheckToken.map(Self.isValidHeaderValue) == true else {
            throw APIError.appCheckInvalid
        }

        let boundary = "SumaiGuard-\(UUID().uuidString)"
        var multipartBody: Data? = Self.multipartBody(
            imageData: image.data,
            boundary: boundary
        )
        var request = URLRequest(url: origin.analysisEndpoint)
        request.httpMethod = "POST"
        request.cachePolicy = .reloadIgnoringLocalCacheData
        request.timeoutInterval = 120
        request.setValue("no-store", forHTTPHeaderField: "Cache-Control")
        request.setValue("application/json", forHTTPHeaderField: "Accept")
        request.setValue("multipart/form-data; boundary=\(boundary)", forHTTPHeaderField: "Content-Type")
        request.httpBody = multipartBody
        request.setValue(appCheckToken, forHTTPHeaderField: "X-Firebase-AppCheck")

        defer {
            appCheckToken = nil
            multipartBody = nil
            request.httpBody = nil
        }

        let data: Data
        let response: URLResponse
        do {
            let loader = BoundedResponseLoader(maximumBytes: maximumResponseBytes)
            (data, response) = try await loader.load(
                request: request,
                configuration: Self.makeSessionConfiguration(protocolClasses: protocolClasses)
            )
        } catch is CancellationError {
            throw CancellationError()
        } catch is BoundedResponseLoaderError {
            throw APIError.invalidResponse
        } catch let error as URLError where error.code == .cancelled {
            throw CancellationError()
        } catch {
            throw APIError.network
        }

        try Task.checkCancellation()
        guard
            let httpResponse = response as? HTTPURLResponse,
            Self.isJSON(response: httpResponse)
        else {
            throw APIError.invalidResponse
        }

        guard (200...299).contains(httpResponse.statusCode) else {
            throw ServerErrorEnvelope.map(statusCode: httpResponse.statusCode, body: data)
        }

        do {
            return try JSONDecoder.sumai.decode(AnalysisResponse.self, from: data)
        } catch {
            throw APIError.invalidResponse
        }
    }

    private static func isValidHeaderValue(_ value: String) -> Bool {
        guard !value.isEmpty, value.utf8.count <= 8_192 else {
            return false
        }
        return value.utf8.allSatisfy { (0x21...0x7E).contains($0) }
    }

    private static func isJSON(response: HTTPURLResponse) -> Bool {
        guard let rawValue = response.value(forHTTPHeaderField: "Content-Type") else {
            return false
        }
        return rawValue
            .split(separator: ";", maxSplits: 1)
            .first?
            .trimmingCharacters(in: .whitespacesAndNewlines)
            .lowercased() == "application/json"
    }

    private static func multipartBody(imageData: Data, boundary: String) -> Data {
        var body = Data()
        body.appendUTF8("--\(boundary)\r\n")
        body.appendUTF8("Content-Disposition: form-data; name=\"image\"; filename=\"sumaiguard-upload.jpg\"\r\n")
        body.appendUTF8("Content-Type: image/jpeg\r\n\r\n")
        body.append(imageData)
        body.appendUTF8("\r\n--\(boundary)\r\n")
        body.appendUTF8("Content-Disposition: form-data; name=\"room_hint\"\r\n\r\n")
        body.appendUTF8("auto\r\n")
        body.appendUTF8("--\(boundary)--\r\n")
        return body
    }
}

enum BoundedResponseLoaderError: Error, Equatable, Sendable {
    case responseTooLarge
    case missingResponse
}

final class BoundedResponseLoader: NSObject, URLSessionDataDelegate, @unchecked Sendable {
    private typealias Continuation = CheckedContinuation<(Data, URLResponse), any Error>

    private struct CompletionAction {
        let continuation: Continuation
        let result: Result<(Data, URLResponse), any Error>
        let session: URLSession?
        let task: URLSessionDataTask?
        let shouldCancel: Bool
    }

    private let maximumBytes: Int
    private let lock = NSLock()
    private var continuation: Continuation?
    private var session: URLSession?
    private var task: URLSessionDataTask?
    private var response: URLResponse?
    private var receivedData = Data()
    private var cancellationRequested = false
    private var isFinished = false

    init(maximumBytes: Int) {
        precondition(maximumBytes > 0)
        self.maximumBytes = maximumBytes
    }

    func load(
        request: URLRequest,
        configuration: URLSessionConfiguration
    ) async throws -> (Data, URLResponse) {
        try Task.checkCancellation()
        return try await withTaskCancellationHandler {
            try await withCheckedThrowingContinuation { continuation in
                start(
                    request: request,
                    configuration: configuration,
                    continuation: continuation
                )
            }
        } onCancel: {
            self.cancel()
        }
    }

    private func start(
        request: URLRequest,
        configuration: URLSessionConfiguration,
        continuation: Continuation
    ) {
        let delegateQueue = OperationQueue()
        delegateQueue.maxConcurrentOperationCount = 1
        delegateQueue.qualityOfService = .userInitiated
        let session = URLSession(
            configuration: configuration,
            delegate: self,
            delegateQueue: delegateQueue
        )
        let task = session.dataTask(with: request)

        let shouldStart = lock.withLock { () -> Bool in
            guard !isFinished, !cancellationRequested else {
                isFinished = true
                return false
            }
            self.continuation = continuation
            self.session = session
            self.task = task
            return true
        }

        guard shouldStart else {
            task.cancel()
            session.invalidateAndCancel()
            continuation.resume(throwing: CancellationError())
            return
        }

        task.resume()
    }

    private func cancel() {
        let activeTask = lock.withLock { () -> URLSessionDataTask? in
            cancellationRequested = true
            return task
        }
        activeTask?.cancel()
    }

    private func fail(_ error: any Error) {
        let action = lock.withLock {
            let finalError: any Error = cancellationRequested ? CancellationError() : error
            return takeCompletionLocked(result: .failure(finalError), shouldCancel: true)
        }
        complete(action)
    }

    private func complete(_ action: CompletionAction?) {
        guard let action else {
            return
        }
        if action.shouldCancel {
            action.task?.cancel()
            action.session?.invalidateAndCancel()
        } else {
            action.session?.finishTasksAndInvalidate()
        }
        action.continuation.resume(with: action.result)
    }

    private func takeCompletionLocked(
        result: Result<(Data, URLResponse), any Error>,
        shouldCancel: Bool
    ) -> CompletionAction? {
        guard !isFinished, let continuation else {
            return nil
        }
        isFinished = true
        let action = CompletionAction(
            continuation: continuation,
            result: result,
            session: session,
            task: task,
            shouldCancel: shouldCancel
        )
        self.continuation = nil
        session = nil
        task = nil
        response = nil
        receivedData = Data()
        return action
    }

    func urlSession(
        _ session: URLSession,
        dataTask: URLSessionDataTask,
        didReceive response: URLResponse,
        completionHandler: @escaping @Sendable (URLSession.ResponseDisposition) -> Void
    ) {
        enum ResponseDecision {
            case allow
            case cancel
            case responseTooLarge
        }

        let decision = lock.withLock { () -> ResponseDecision in
            guard !isFinished, !cancellationRequested else {
                return .cancel
            }
            guard response.expectedContentLength <= Int64(maximumBytes) else {
                return .responseTooLarge
            }
            self.response = response
            return .allow
        }

        switch decision {
        case .allow:
            completionHandler(.allow)
        case .cancel:
            completionHandler(.cancel)
        case .responseTooLarge:
            completionHandler(.cancel)
            fail(BoundedResponseLoaderError.responseTooLarge)
        }
    }

    func urlSession(
        _ session: URLSession,
        dataTask: URLSessionDataTask,
        didReceive data: Data
    ) {
        let exceededLimit = lock.withLock { () -> Bool in
            guard !isFinished, !cancellationRequested else {
                return false
            }
            guard data.count <= maximumBytes - receivedData.count else {
                return true
            }
            receivedData.append(data)
            return false
        }

        if exceededLimit {
            fail(BoundedResponseLoaderError.responseTooLarge)
        }
    }

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        didCompleteWithError error: (any Error)?
    ) {
        let wasCancelled = lock.withLock { cancellationRequested }
        if wasCancelled {
            let action = lock.withLock {
                takeCompletionLocked(
                    result: .failure(CancellationError()),
                    shouldCancel: true
                )
            }
            complete(action)
            return
        }

        if let error {
            fail(error)
            return
        }

        let action = lock.withLock { () -> CompletionAction? in
            guard let response else {
                return takeCompletionLocked(
                    result: .failure(BoundedResponseLoaderError.missingResponse),
                    shouldCancel: true
                )
            }
            return takeCompletionLocked(
                result: .success((receivedData, response)),
                shouldCancel: false
            )
        }
        complete(action)
    }

    func urlSession(
        _ session: URLSession,
        task: URLSessionTask,
        willPerformHTTPRedirection response: HTTPURLResponse,
        newRequest request: URLRequest,
        completionHandler: @escaping @Sendable (URLRequest?) -> Void
    ) {
        completionHandler(nil)
    }
}

private extension Data {
    mutating func appendUTF8(_ string: String) {
        append(contentsOf: string.utf8)
    }
}
