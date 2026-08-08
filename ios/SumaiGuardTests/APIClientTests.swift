import Foundation
@testable import SumaiGuard
import XCTest

final class APIClientTests: XCTestCase {
    override func setUp() {
        super.setUp()
        StubURLProtocol.state.reset()
    }

    func testInvalidOrLoopbackReleaseOriginIsRejected() {
        let invalidOrigins = [
            "http://api.example.com",
            "https://user:password@api.example.com",
            "https://api.example.com/path",
            "https://api.example.com?token=secret",
            "https://api.example.com#fragment",
            "https://localhost",
            "https://foo.localhost",
            "https://127.0.0.1",
            "https://127.0.0.2",
            "https://[::1]",
            "https://192.0.2.1",
            "https://api.example.com:443",
            "https://api.example.com:8443",
            "not a URL",
        ]

        for rawValue in invalidOrigins {
            XCTAssertThrowsError(try APIOrigin(rawValue), rawValue)
        }
    }

    func testRejectsLegacyNumericAndEncodedHostSyntaxWithoutResolution() {
        let numericOrEncodedOrigins = [
            "https://127.1",
            "https://127.0.1",
            "https://0177.1",
            "https://0x7f.1",
            "https://0X7F.0.0.1",
            "https://2130706433",
            "https://017700000001",
            "https://0x7f000001",
            "https://%31%32%37.0.0.1",
            "https://api.example.com.",
            "https://[2001:db8::1]",
        ]

        for rawValue in numericOrEncodedOrigins {
            XCTAssertThrowsError(try APIOrigin(rawValue), rawValue)
        }
    }

    func testValidOriginIsNormalizedAndEndpointIsAppendedExactlyOnce() throws {
        let origin = try APIOrigin("HTTPS://API2.Example.COM")

        XCTAssertEqual(origin.url.absoluteString, "https://api2.example.com")
        XCTAssertEqual(origin.analysisEndpoint.absoluteString, "https://api2.example.com/api/v1/analyze")
    }

    func testRequestUsesEphemeralSessionAndNoCache() {
        let configuration = APIClient.makeSessionConfiguration(protocolClasses: [StubURLProtocol.self])

        XCTAssertEqual(configuration.urlCache, nil)
        XCTAssertEqual(configuration.requestCachePolicy, .reloadIgnoringLocalCacheData)
        XCTAssertEqual(configuration.timeoutIntervalForRequest, 120)
        XCTAssertEqual(configuration.httpCookieStorage, nil)
        XCTAssertFalse(configuration.httpShouldSetCookies)
        XCTAssertEqual(configuration.urlCredentialStorage, nil)
        guard let protocolClass = configuration.protocolClasses?.first else {
            XCTFail("The injected URLProtocol must be retained")
            return
        }
        XCTAssertEqual(ObjectIdentifier(protocolClass), ObjectIdentifier(StubURLProtocol.self))
    }

    func testAppCheckTokenAppearsOnlyInHeader() async throws {
        let secret = "SECRET.APP_CHECK.TOKEN"
        StubURLProtocol.state.respond(status: 200, contentType: "application/json; charset=utf-8", body: try fixture("analysis-applicable"))
        let client = try makeClient(token: secret)

        _ = try await client.analyze(image: testImage, roomHint: "auto")

        let request = try XCTUnwrap(StubURLProtocol.state.requests.first)
        XCTAssertEqual(request.headers["X-Firebase-AppCheck"], secret)
        XCTAssertFalse(request.url.contains(secret))
        XCTAssertFalse(String(decoding: request.body, as: UTF8.self).contains(secret))
    }

    func testMultipartContainsOneJPEGAndFixedAutoRoomHint() async throws {
        StubURLProtocol.state.respond(status: 200, contentType: "application/json", body: try fixture("analysis-applicable"))
        let client = try makeClient(token: "token")
        let hostileImage = SanitizedImage(
            data: Data([0xFF, 0xD8, 0x00, 0xFF, 0xD9]),
            pixelWidth: 1,
            pixelHeight: 1,
            mimeType: "text/plain\r\nX-Evil: yes",
            filename: "bad.jpg\"\r\nX-Evil: yes"
        )

        _ = try await client.analyze(image: hostileImage, roomHint: "x\r\nX-Evil: yes")

        let request = try XCTUnwrap(StubURLProtocol.state.requests.first)
        XCTAssertEqual(request.method, "POST")
        XCTAssertEqual(request.headers["Cache-Control"], "no-store")
        XCTAssertEqual(request.headers["Accept"], "application/json")
        let contentType = try XCTUnwrap(request.headers["Content-Type"])
        XCTAssertTrue(contentType.hasPrefix("multipart/form-data; boundary="))
        let body = String(decoding: request.body, as: UTF8.self)
        XCTAssertEqual(body.components(separatedBy: "name=\"image\"").count - 1, 1)
        XCTAssertEqual(body.components(separatedBy: "Content-Type: image/jpeg").count - 1, 1)
        XCTAssertTrue(body.contains("filename=\"sumaiguard-upload.jpg\""))
        XCTAssertEqual(body.components(separatedBy: "name=\"room_hint\"").count - 1, 1)
        XCTAssertTrue(body.contains("\r\n\r\nauto\r\n"))
        XCTAssertFalse(body.contains("X-Evil"))
        XCTAssertFalse(body.contains("bad.jpg"))
    }

    func testServerErrorMapsFromStableStatusAndCodeOnly() async throws {
        let secretDetail = "SECRET_PROVIDER_DETAIL"
        let body = Data(#"{"error":"APP_CHECK_INVALID","message":"safe","detail":"SECRET_PROVIDER_DETAIL"}"#.utf8)
        StubURLProtocol.state.respond(status: 401, contentType: "application/json", body: body)
        let client = try makeClient(token: "token")

        do {
            _ = try await client.analyze(image: testImage, roomHint: "auto")
            XCTFail("A non-2xx response must fail")
        } catch {
            XCTAssertEqual(error as? APIError, .appCheckInvalid)
            XCTAssertFalse(String(describing: error).contains(secretDetail))
        }
    }

    func testMismatchedStableErrorAndStatusFailsClosedWithoutRetry() async throws {
        let body = Data(#"{"error":"APP_CHECK_INVALID","message":"detail"}"#.utf8)
        StubURLProtocol.state.respond(status: 500, contentType: "application/json", body: body)
        let client = try makeClient(token: "token")

        do {
            _ = try await client.analyze(image: testImage, roomHint: "auto")
            XCTFail("A mismatched status and stable code must fail")
        } catch {
            XCTAssertEqual(error as? APIError, .invalidResponse)
            XCTAssertEqual(StubURLProtocol.state.requests.count, 1)
        }
    }

    func testRedirectDelegateRejectsEveryRedirectRequest() throws {
        let configuration = APIClient.makeSessionConfiguration(protocolClasses: [StubURLProtocol.self])
        let delegate = BoundedResponseLoader(maximumBytes: 64)
        let session = URLSession(configuration: configuration, delegate: delegate, delegateQueue: nil)
        defer { session.invalidateAndCancel() }
        let originalURL = try XCTUnwrap(URL(string: "https://api.example.com/api/v1/analyze"))
        let redirectedURL = try XCTUnwrap(URL(string: "https://evil.example.net/collect"))
        let response = try XCTUnwrap(
            HTTPURLResponse(
                url: originalURL,
                statusCode: 307,
                httpVersion: "HTTP/1.1",
                headerFields: ["Location": redirectedURL.absoluteString]
            )
        )
        let task = session.dataTask(with: originalURL)
        let decision = RedirectDecision(initialValue: URLRequest(url: redirectedURL))

        delegate.urlSession(
            session,
            task: task,
            willPerformHTTPRedirection: response,
            newRequest: URLRequest(url: redirectedURL)
        ) { request in
            decision.value = request
        }

        XCTAssertNil(decision.value)
    }

    func testRejectsMalformedJSONOrWrongContentType() async throws {
        for (contentType, body) in [
            ("text/html", try fixture("analysis-applicable")),
            ("application/json", Data("not json".utf8)),
        ] {
            StubURLProtocol.state.reset()
            StubURLProtocol.state.respond(status: 200, contentType: contentType, body: body)
            let client = try makeClient(token: "token")

            do {
                _ = try await client.analyze(image: testImage, roomHint: "auto")
                XCTFail("Malformed or non-JSON responses must fail closed")
            } catch {
                XCTAssertEqual(error as? APIError, .invalidResponse)
            }
        }
    }

    func testChunkedResponseCancelsAtLimitWithoutConsumingLaterChunks() async throws {
        StubURLProtocol.state.respondInChunks(
            status: 200,
            headers: ["Content-Type": "application/json"],
            chunks: [
                Data(repeating: 0x20, count: 40),
                Data(repeating: 0x20, count: 30),
                Data("must-not-be-consumed".utf8),
            ]
        )
        let client = try makeClient(token: "token", maximumResponseBytes: 64)

        do {
            _ = try await client.analyze(image: testImage, roomHint: "auto")
            XCTFail("Oversized responses must fail closed")
        } catch {
            XCTAssertEqual(error as? APIError, .invalidResponse)
        }

        try await Task.sleep(for: .milliseconds(250))
        XCTAssertTrue(StubURLProtocol.state.didStop)
        XCTAssertEqual(StubURLProtocol.state.emittedChunkCount, 2)
    }

    func testContentLengthOverLimitCancelsBeforeReceivingBody() async throws {
        StubURLProtocol.state.respondInChunks(
            status: 200,
            headers: [
                "Content-Type": "application/json",
                "Content-Length": "65",
            ],
            chunks: [try fixture("analysis-applicable")]
        )
        let client = try makeClient(token: "token", maximumResponseBytes: 64)

        do {
            _ = try await client.analyze(image: testImage, roomHint: "auto")
            XCTFail("An oversized declared response must fail before consuming body bytes")
        } catch {
            XCTAssertEqual(error as? APIError, .invalidResponse)
        }

        try await Task.sleep(for: .milliseconds(250))
        XCTAssertTrue(StubURLProtocol.state.didStop)
        XCTAssertEqual(StubURLProtocol.state.emittedChunkCount, 0)
    }

    func testChunkedResponseWithinLimitDecodesNormally() async throws {
        let body = try fixture("analysis-applicable")
        let firstBoundary = body.count / 3
        let secondBoundary = firstBoundary * 2
        StubURLProtocol.state.respondInChunks(
            status: 200,
            headers: ["Content-Type": "application/json"],
            chunks: [
                body.subdata(in: 0..<firstBoundary),
                body.subdata(in: firstBoundary..<secondBoundary),
                body.subdata(in: secondBoundary..<body.count),
            ]
        )
        let client = try makeClient(token: "token", maximumResponseBytes: body.count)

        let response = try await client.analyze(image: testImage, roomHint: "auto")

        XCTAssertFalse(response.analysisID.isEmpty)
        XCTAssertEqual(StubURLProtocol.state.emittedChunkCount, 3)
    }

    func testRejectsHeaderInjectionBeforeStartingRequest() async throws {
        let client = try makeClient(token: "token\r\nX-Evil: yes")

        do {
            _ = try await client.analyze(image: testImage, roomHint: "auto")
            XCTFail("Header injection must fail")
        } catch {
            XCTAssertEqual(error as? APIError, .appCheckInvalid)
            XCTAssertEqual(StubURLProtocol.state.requests.count, 0)
        }
    }

    func testTokenFailureUsesStableErrorAndStartsNoRequest() async throws {
        let client = try makeClient(tokenProvider: FailingTokenProvider())

        do {
            _ = try await client.analyze(image: testImage, roomHint: "auto")
            XCTFail("Token failure must fail closed")
        } catch {
            XCTAssertEqual(error as? APIError, .appCheckInvalid)
            XCTAssertEqual(StubURLProtocol.state.requests.count, 0)
            XCTAssertFalse(String(describing: error).contains("SECRET_TOKEN_PROVIDER_DETAIL"))
        }
    }

    func testCancellationCancelsURLTaskAndPropagatesCancellationError() async throws {
        StubURLProtocol.state.hang()
        let client = try makeClient(token: "token")
        let image = testImage
        let task = Task { try await client.analyze(image: image, roomHint: "auto") }
        try await waitForRequestCount(1)

        task.cancel()

        do {
            _ = try await task.value
            XCTFail("A cancelled upload must not return")
        } catch is CancellationError {
            XCTAssertTrue(StubURLProtocol.state.didStop)
            XCTAssertEqual(StubURLProtocol.state.requests.count, 1)
        } catch {
            XCTFail("Expected CancellationError, received \(type(of: error))")
        }
    }
}

private extension APIClientTests {
    var testImage: SanitizedImage {
        SanitizedImage(
            data: Data([0xFF, 0xD8, 0x00, 0xFF, 0xD9]),
            pixelWidth: 1,
            pixelHeight: 1,
            mimeType: "image/jpeg",
            filename: "sumaiguard-upload.jpg"
        )
    }

    func fixture(_ name: String) throws -> Data {
        let url = try XCTUnwrap(Bundle(for: Self.self).url(forResource: name, withExtension: "json"))
        return try Data(contentsOf: url)
    }

    func makeClient(token: String, maximumResponseBytes: Int = 10 * 1_024 * 1_024) throws -> APIClient {
        try makeClient(tokenProvider: FixedTokenProvider(value: token), maximumResponseBytes: maximumResponseBytes)
    }

    func makeClient(
        tokenProvider: any AppCheckTokenProviding,
        maximumResponseBytes: Int = 10 * 1_024 * 1_024
    ) throws -> APIClient {
        return APIClient(
            origin: try APIOrigin("https://api.example.com"),
            tokenProvider: tokenProvider,
            protocolClasses: [StubURLProtocol.self],
            maximumResponseBytes: maximumResponseBytes
        )
    }

    func waitForRequestCount(_ expectedCount: Int) async throws {
        for _ in 0..<100 where StubURLProtocol.state.requests.count < expectedCount {
            try await Task.sleep(for: .milliseconds(10))
        }
        XCTAssertEqual(StubURLProtocol.state.requests.count, expectedCount)
    }
}

private struct FixedTokenProvider: AppCheckTokenProviding {
    let value: String

    func token() async throws -> String {
        value
    }
}

private struct FailingTokenProvider: AppCheckTokenProviding {
    struct SecretError: Error, CustomStringConvertible {
        var description: String { "SECRET_TOKEN_PROVIDER_DETAIL" }
    }

    func token() async throws -> String {
        throw SecretError()
    }
}

private final class StubURLProtocolState: @unchecked Sendable {
    struct RecordedRequest: Sendable {
        let url: String
        let method: String
        let headers: [String: String]
        let body: Data
    }

    enum Behavior: @unchecked Sendable {
        case response(status: Int, contentType: String, body: Data)
        case chunked(status: Int, headers: [String: String], chunks: [Data])
        case hanging
    }

    private let lock = NSLock()
    private var behavior: Behavior = .response(status: 500, contentType: "application/json", body: Data())
    private var recordedRequests: [RecordedRequest] = []
    private var stopped = false
    private var chunkCount = 0

    var requests: [RecordedRequest] {
        lock.withLock { recordedRequests }
    }

    var didStop: Bool {
        lock.withLock { stopped }
    }

    var emittedChunkCount: Int {
        lock.withLock { chunkCount }
    }

    func reset() {
        lock.withLock {
            behavior = .response(status: 500, contentType: "application/json", body: Data())
            recordedRequests = []
            stopped = false
            chunkCount = 0
        }
    }

    func respond(status: Int, contentType: String, body: Data) {
        lock.withLock {
            behavior = .response(status: status, contentType: contentType, body: body)
        }
    }

    func respondInChunks(status: Int, headers: [String: String], chunks: [Data]) {
        lock.withLock {
            behavior = .chunked(status: status, headers: headers, chunks: chunks)
        }
    }

    func hang() {
        lock.withLock { behavior = .hanging }
    }

    func begin(request: URLRequest) -> Behavior {
        lock.withLock {
            recordedRequests.append(
                RecordedRequest(
                    url: request.url?.absoluteString ?? "",
                    method: request.httpMethod ?? "",
                    headers: request.allHTTPHeaderFields ?? [:],
                    body: Self.readBody(from: request)
                )
            )
            return behavior
        }
    }

    func beginEmittingChunk() -> Bool {
        lock.withLock {
            guard !stopped else {
                return false
            }
            chunkCount += 1
            return true
        }
    }

    var canFinish: Bool {
        lock.withLock { !stopped }
    }

    func stop() {
        lock.withLock { stopped = true }
    }

    private static func readBody(from request: URLRequest) -> Data {
        if let body = request.httpBody {
            return body
        }
        guard let stream = request.httpBodyStream else {
            return Data()
        }

        stream.open()
        defer { stream.close() }
        var body = Data()
        var buffer = [UInt8](repeating: 0, count: 4_096)
        while true {
            let count = stream.read(&buffer, maxLength: buffer.count)
            guard count > 0 else {
                return body
            }
            body.append(contentsOf: buffer.prefix(count))
        }
    }
}

private final class RedirectDecision: @unchecked Sendable {
    private let lock = NSLock()
    private var storedValue: URLRequest?

    init(initialValue: URLRequest?) {
        storedValue = initialValue
    }

    var value: URLRequest? {
        get { lock.withLock { storedValue } }
        set { lock.withLock { storedValue = newValue } }
    }
}

private final class StubURLProtocol: URLProtocol, @unchecked Sendable {
    static let state = StubURLProtocolState()
    private let workerLock = NSLock()
    private var worker: Thread?

    override class func canInit(with request: URLRequest) -> Bool { true }
    override class func canonicalRequest(for request: URLRequest) -> URLRequest { request }

    override func startLoading() {
        guard let client else { return }
        switch Self.state.begin(request: request) {
        case let .response(status, contentType, body):
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: status,
                httpVersion: "HTTP/1.1",
                headerFields: ["Content-Type": contentType]
            )!
            client.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            client.urlProtocol(self, didLoad: body)
            client.urlProtocolDidFinishLoading(self)
        case let .chunked(status, headers, chunks):
            let response = HTTPURLResponse(
                url: request.url!,
                statusCode: status,
                httpVersion: "HTTP/1.1",
                headerFields: headers
            )!
            client.urlProtocol(self, didReceive: response, cacheStoragePolicy: .notAllowed)
            let worker = Thread { [weak self] in
                self?.emit(chunks: chunks)
            }
            worker.name = "SumaiGuardTests.StubURLProtocol"
            workerLock.withLock { self.worker = worker }
            worker.start()
        case .hanging:
            break
        }
    }

    override func stopLoading() {
        Self.state.stop()
        workerLock.withLock { worker }?.cancel()
    }

    private func emit(chunks: [Data]) {
        for chunk in chunks {
            Thread.sleep(forTimeInterval: 0.1)
            guard
                !Thread.current.isCancelled,
                Self.state.beginEmittingChunk()
            else {
                return
            }
            client?.urlProtocol(self, didLoad: chunk)
        }

        guard !Thread.current.isCancelled, Self.state.canFinish else {
            return
        }
        client?.urlProtocolDidFinishLoading(self)
    }
}
