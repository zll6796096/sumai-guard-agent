import Foundation

enum RoomType: String, Decodable, Equatable, Sendable {
    case genkan
    case hallway
    case bathroom
    case toilet
    case bedroom
    case kitchen
    case auto
}

enum OverallRiskLevel: String, Decodable, Equatable, Sendable {
    case low
    case medium
    case high
}

enum ActionTier: String, Decodable, Equatable, Sendable {
    case familyNoCost = "FAMILY_NO_COST"
    case careManagerPurchase = "CARE_MANAGER_PURCHASE"
    case contractorConstruction = "CONTRACTOR_CONSTRUCTION"
}

enum CostLevel: String, Decodable, Equatable, Sendable {
    case zero = "ZERO"
    case low = "LOW"
    case medium = "MEDIUM"
    case high = "HIGH"
}

enum OntologyRuleKind: String, Decodable, Equatable, Sendable {
    case visibleHazard = "visible_hazard"
    case expectedFeature = "expected_feature"
}

struct BoundingBox: Decodable, Equatable, Sendable {
    let x: Double
    let y: Double
    let w: Double
    let h: Double

    private enum CodingKeys: String, CodingKey {
        case x
        case y
        case w
        case h
    }
}

extension BoundingBox {
    init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        x = try container.decode(Double.self, forKey: .x)
        y = try container.decode(Double.self, forKey: .y)
        w = try container.decode(Double.self, forKey: .w)
        h = try container.decode(Double.self, forKey: .h)

        guard (0.0...1.0).contains(x), (0.0...1.0).contains(y) else {
            throw DecodingError.dataCorruptedError(
                forKey: x < 0.0 || x > 1.0 ? .x : .y,
                in: container,
                debugDescription: "Bounding-box origins must be normalized from zero through one."
            )
        }
        guard w > 0.0, w <= 1.0, h > 0.0, h <= 1.0 else {
            throw DecodingError.dataCorruptedError(
                forKey: w <= 0.0 || w > 1.0 ? .w : .h,
                in: container,
                debugDescription: "Bounding-box dimensions must be greater than zero and at most one."
            )
        }

        let tolerance = 1e-9
        guard x + w <= 1.0 + tolerance, y + h <= 1.0 + tolerance else {
            throw DecodingError.dataCorruptedError(
                forKey: x + w > 1.0 + tolerance ? .w : .h,
                in: container,
                debugDescription: "Bounding box must fit inside the normalized image frame."
            )
        }
    }
}

struct RiskFinding: Decodable, Equatable, Identifiable, Sendable {
    let id: String
    let riskType: String
    let labelJA: String
    let descriptionJA: String
    let severity: Int
    let confidence: Double
    let bbox: BoundingBox
    let displayBBox: BoundingBox?
    let evidenceSourceIDs: [String]
    let evidenceJA: String
    let basisLabelJA: String
    let basisSummaryJA: String
    let needsHumanConfirmation: Bool
    let ontologyKey: String?
    let ontologyRuleKind: OntologyRuleKind?

    private enum CodingKeys: String, CodingKey {
        case id
        case riskType = "risk_type"
        case labelJA = "label_ja"
        case descriptionJA = "description_ja"
        case severity
        case confidence
        case bbox
        case displayBBox = "display_bbox"
        case evidenceSourceIDs = "evidence_source_ids"
        case evidenceJA = "evidence_ja"
        case basisLabelJA = "basis_label_ja"
        case basisSummaryJA = "basis_summary_ja"
        case needsHumanConfirmation = "needs_human_confirmation"
        case ontologyKey = "ontology_key"
        case ontologyRuleKind = "ontology_rule_kind"
    }
}

extension RiskFinding {
    init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        id = try container.decode(String.self, forKey: .id)
        riskType = try container.decode(String.self, forKey: .riskType)
        labelJA = try container.decode(String.self, forKey: .labelJA)
        descriptionJA = try container.decode(String.self, forKey: .descriptionJA)
        severity = try container.decode(Int.self, forKey: .severity)
        confidence = try container.decode(Double.self, forKey: .confidence)
        bbox = try container.decode(BoundingBox.self, forKey: .bbox)
        displayBBox = try container.decode(BoundingBox?.self, forKey: .displayBBox)
        evidenceSourceIDs = try container.decode([String].self, forKey: .evidenceSourceIDs)
        evidenceJA = try container.decode(String.self, forKey: .evidenceJA)
        basisLabelJA = try container.decode(String.self, forKey: .basisLabelJA)
        basisSummaryJA = try container.decode(String.self, forKey: .basisSummaryJA)
        needsHumanConfirmation = try container.decode(Bool.self, forKey: .needsHumanConfirmation)
        ontologyKey = try container.decode(String?.self, forKey: .ontologyKey)
        ontologyRuleKind = try container.decode(OntologyRuleKind?.self, forKey: .ontologyRuleKind)

        guard (1...5).contains(severity) else {
            throw DecodingError.dataCorruptedError(
                forKey: .severity,
                in: container,
                debugDescription: "Severity must be from one through five."
            )
        }
        guard (0.0...1.0).contains(confidence) else {
            throw DecodingError.dataCorruptedError(
                forKey: .confidence,
                in: container,
                debugDescription: "Confidence must be normalized from zero through one."
            )
        }
    }
}

struct ActionItem: Decodable, Equatable, Identifiable, Sendable {
    let id: String
    let riskID: String
    let tier: ActionTier
    let titleJA: String
    let descriptionJA: String
    let whyJA: String
    let costLevel: CostLevel
    let requiresProfessional: Bool
    let disclaimerJA: String

    private enum CodingKeys: String, CodingKey {
        case id
        case riskID = "risk_id"
        case tier
        case titleJA = "title_ja"
        case descriptionJA = "description_ja"
        case whyJA = "why_ja"
        case costLevel = "cost_level"
        case requiresProfessional = "requires_professional"
        case disclaimerJA = "disclaimer_ja"
    }
}

struct ActionPlan: Decodable, Equatable, Sendable {
    let familyNoCost: [ActionItem]
    let careManagerPurchase: [ActionItem]
    let contractorConstruction: [ActionItem]

    var isEmpty: Bool {
        familyNoCost.isEmpty && careManagerPurchase.isEmpty && contractorConstruction.isEmpty
    }

    private enum CodingKeys: String, CodingKey {
        case familyNoCost = "family_no_cost"
        case careManagerPurchase = "care_manager_purchase"
        case contractorConstruction = "contractor_construction"
    }
}

struct AnalysisResponse: Decodable, Equatable, Identifiable, Sendable {
    let analysisID: String
    let roomType: RoomType
    let overallRiskLevel: OverallRiskLevel
    let findings: [RiskFinding]
    let actionPlan: ActionPlan
    let annotatedImageBase64: String
    let improvementImageBase64: String
    let riskSummaryMarkdown: String
    let familyActionsMarkdown: String
    let careManagerActionsMarkdown: String
    let contractorActionsMarkdown: String
    let disclaimerJA: String
    let mode: String
    let isHomeEnvironment: Bool
    let isNotApplicable: Bool
    let notApplicableReasonJA: String?
    let model: String
    let resultKey: String
    let semanticHash: String
    let schemaVersion: String
    let ontologyVersion: String
    let preprocessVersion: String
    let inferenceConfigVersion: String
    let stageTimingsMS: [String: Int]

    var id: String {
        analysisID
    }

    private enum CodingKeys: String, CodingKey {
        case analysisID = "analysis_id"
        case roomType = "room_type"
        case overallRiskLevel = "overall_risk_level"
        case findings
        case actionPlan = "action_plan"
        case annotatedImageBase64 = "annotated_image_base64"
        case improvementImageBase64 = "improvement_image_base64"
        case riskSummaryMarkdown = "risk_summary_markdown"
        case familyActionsMarkdown = "family_actions_markdown"
        case careManagerActionsMarkdown = "care_manager_actions_markdown"
        case contractorActionsMarkdown = "contractor_actions_markdown"
        case disclaimerJA = "disclaimer_ja"
        case mode
        case isHomeEnvironment = "is_home_environment"
        case isNotApplicable = "is_not_applicable"
        case notApplicableReasonJA = "not_applicable_reason_ja"
        case model
        case resultKey = "result_key"
        case semanticHash = "semantic_hash"
        case schemaVersion = "schema_version"
        case ontologyVersion = "ontology_version"
        case preprocessVersion = "preprocess_version"
        case inferenceConfigVersion = "inference_config_version"
        case stageTimingsMS = "stage_timings_ms"
    }
}

extension AnalysisResponse {
    init(from decoder: any Decoder) throws {
        let container = try decoder.container(keyedBy: CodingKeys.self)
        analysisID = try container.decode(String.self, forKey: .analysisID)
        roomType = try container.decode(RoomType.self, forKey: .roomType)
        overallRiskLevel = try container.decode(OverallRiskLevel.self, forKey: .overallRiskLevel)
        findings = try container.decode([RiskFinding].self, forKey: .findings)
        actionPlan = try container.decode(ActionPlan.self, forKey: .actionPlan)
        annotatedImageBase64 = try container.decode(String.self, forKey: .annotatedImageBase64)
        improvementImageBase64 = try container.decode(String.self, forKey: .improvementImageBase64)
        riskSummaryMarkdown = try container.decode(String.self, forKey: .riskSummaryMarkdown)
        familyActionsMarkdown = try container.decode(String.self, forKey: .familyActionsMarkdown)
        careManagerActionsMarkdown = try container.decode(String.self, forKey: .careManagerActionsMarkdown)
        contractorActionsMarkdown = try container.decode(String.self, forKey: .contractorActionsMarkdown)
        disclaimerJA = try container.decode(String.self, forKey: .disclaimerJA)
        mode = try container.decode(String.self, forKey: .mode)
        isHomeEnvironment = try container.decode(Bool.self, forKey: .isHomeEnvironment)
        isNotApplicable = try container.decode(Bool.self, forKey: .isNotApplicable)
        notApplicableReasonJA = try container.decode(String?.self, forKey: .notApplicableReasonJA)
        model = try container.decode(String.self, forKey: .model)
        resultKey = try container.decode(String.self, forKey: .resultKey)
        semanticHash = try container.decode(String.self, forKey: .semanticHash)
        schemaVersion = try container.decode(String.self, forKey: .schemaVersion)
        ontologyVersion = try container.decode(String.self, forKey: .ontologyVersion)
        preprocessVersion = try container.decode(String.self, forKey: .preprocessVersion)
        inferenceConfigVersion = try container.decode(String.self, forKey: .inferenceConfigVersion)
        stageTimingsMS = try container.decode([String: Int].self, forKey: .stageTimingsMS)

        if isNotApplicable {
            guard roomType == .auto, overallRiskLevel == .low else {
                throw DecodingError.dataCorruptedError(
                    forKey: .isNotApplicable,
                    in: container,
                    debugDescription: "Not-applicable responses require auto room and low risk."
                )
            }
            guard findings.isEmpty, actionPlan.isEmpty else {
                throw DecodingError.dataCorruptedError(
                    forKey: .isNotApplicable,
                    in: container,
                    debugDescription: "Not-applicable responses require empty findings and actions."
                )
            }
            guard let reason = notApplicableReasonJA,
                  !reason.trimmingCharacters(in: .whitespacesAndNewlines).isEmpty else {
                throw DecodingError.dataCorruptedError(
                    forKey: .notApplicableReasonJA,
                    in: container,
                    debugDescription: "Not-applicable responses require a nonblank reason."
                )
            }
        } else {
            guard isHomeEnvironment, roomType != .auto, notApplicableReasonJA == nil else {
                throw DecodingError.dataCorruptedError(
                    forKey: .isNotApplicable,
                    in: container,
                    debugDescription: "Applicable responses require a home, a known room, and no not-applicable reason."
                )
            }
        }
    }
}

extension JSONDecoder {
    static var sumai: JSONDecoder {
        JSONDecoder()
    }
}
