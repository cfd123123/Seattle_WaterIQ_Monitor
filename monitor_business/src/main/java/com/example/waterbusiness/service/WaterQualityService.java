package com.example.waterbusiness.service;

import com.example.waterbusiness.client.WaterAIClient;
import com.example.waterbusiness.common.TraceIdFilter;
import com.example.waterbusiness.config.WaterAlertProperties;
import com.example.waterbusiness.domain.PollutionLevelThresholds;
import com.example.waterbusiness.dto.WaterQualityBatchItemResult;
import com.example.waterbusiness.dto.WaterQualityBatchResponse;
import com.example.waterbusiness.dto.MapStationPointResponse;
import com.example.waterbusiness.dto.WaterQualityRequest;
import com.example.waterbusiness.dto.WaterQualityResponse;
import com.example.waterbusiness.entity.AlertEvent;
import com.example.waterbusiness.entity.ModelCallLog;
import com.example.waterbusiness.entity.MonitorStation;
import com.example.waterbusiness.entity.RecordSource;
import com.example.waterbusiness.entity.WaterQualityRecord;
import com.example.waterbusiness.metrics.WaterBusinessMetrics;
import com.example.waterbusiness.repository.AlertEventRepository;
import com.example.waterbusiness.repository.ModelCallLogRepository;
import com.example.waterbusiness.repository.MonitorStationRepository;
import com.example.waterbusiness.repository.WaterQualityRepository;
import com.fasterxml.jackson.core.JsonProcessingException;
import com.fasterxml.jackson.databind.ObjectMapper;
import feign.FeignException;
import jakarta.annotation.PostConstruct;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.slf4j.MDC;
import org.springframework.data.domain.Page;
import org.springframework.data.domain.PageRequest;
import org.springframework.data.domain.Pageable;
import org.springframework.data.domain.Sort;
import org.springframework.stereotype.Service;
import org.springframework.transaction.PlatformTransactionManager;
import org.springframework.transaction.TransactionDefinition;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.transaction.support.TransactionTemplate;
import org.springframework.web.server.ResponseStatusException;
import org.springframework.http.HttpStatus;

import java.time.LocalDateTime;
import java.util.ArrayList;
import java.util.List;
import java.util.Locale;

@Service
@RequiredArgsConstructor
public class WaterQualityService {

    private static final Logger log = LoggerFactory.getLogger(WaterQualityService.class);

    private static final String RULE_CODE = "HARDCODED_LEVEL_THRESHOLD";
    private static final String ALERT_TYPE = "POLLUTION_THRESHOLD";

    private final WaterAIClient waterAIClient;
    private final WaterQualityRepository waterQualityRepository;
    private final MonitorStationRepository monitorStationRepository;
    private final ModelCallLogRepository modelCallLogRepository;
    private final AlertEventRepository alertEventRepository;
    private final WaterAlertProperties waterAlertProperties;
    private final ObjectMapper objectMapper;
    private final PlatformTransactionManager transactionManager;
    private final WaterBusinessMetrics businessMetrics;
    private final AiPredictService aiPredictService;

    /** Separate transactions: error logs and per-row batch commits without rolling back others */
    private TransactionTemplate requiresNewTx;

    @PostConstruct
    void initTransactionTemplates() {
        requiresNewTx = new TransactionTemplate(transactionManager);
        requiresNewTx.setPropagationBehavior(TransactionDefinition.PROPAGATION_REQUIRES_NEW);
    }

    public Page<WaterQualityRecord> listRecords(Pageable pageable) {
        return waterQualityRepository.findAll(
                PageRequest.of(
                        pageable.getPageNumber(),
                        pageable.getPageSize(),
                        Sort.by(Sort.Direction.DESC, "createTime")
                )
        );
    }

    public List<MapStationPointResponse> listMapStations() {
        List<MonitorStation> stations = monitorStationRepository.findAll();
        List<MapStationPointResponse> result = new ArrayList<>(stations.size());
        for (MonitorStation station : stations) {
            WaterQualityRecord latest = waterQualityRepository
                    .findTopByStationIdOrderBySampleTimeDescCreateTimeDesc(station.getId());
            long openAlertCount = alertEventRepository.countByStationIdAndStatusIn(
                    station.getId(),
                    List.of("NEW", "ACK")
            );
            result.add(MapStationPointResponse.builder()
                    .stationId(station.getId())
                    .stationCode(station.getStationCode())
                    .stationName(station.getStationName())
                    .province(station.getProvince())
                    .city(station.getCity())
                    .latitude(station.getLatitude())
                    .longitude(station.getLongitude())
                    .externalId(station.getExternalId())
                    .latestPollutionLevel(latest != null ? latest.getPollutionLevel() : null)
                    .latestSampleTime(latest != null ? latest.getSampleTime() : null)
                    .latestCreateTime(latest != null ? latest.getCreateTime() : null)
                    .openAlertCount(openAlertCount)
                    .build());
        }
        return result;
    }

    @Transactional
    public WaterQualityResponse checkAndSave(WaterQualityRequest request) {
        return performCheckAndSave(request);
    }

    /**
     * Batch check: each row uses {@link TransactionDefinition#PROPAGATION_REQUIRES_NEW}; failures are isolated.
     */
    public WaterQualityBatchResponse checkBatch(List<WaterQualityRequest> items) {
        List<WaterQualityBatchItemResult> results = new ArrayList<>();
        int ok = 0;
        int fail = 0;
        for (int i = 0; i < items.size(); i++) {
            WaterQualityRequest req = items.get(i);
            try {
                WaterQualityResponse r = requiresNewTx.execute(status -> performCheckAndSave(req));
                results.add(WaterQualityBatchItemResult.builder()
                        .index(i)
                        .success(true)
                        .data(r)
                        .build());
                ok++;
                businessMetrics.recordBatchItemSuccess();
            } catch (Exception e) {
                businessMetrics.recordBatchItemFailure();
                results.add(WaterQualityBatchItemResult.builder()
                        .index(i)
                        .success(false)
                        .errorMessage(e.getMessage() != null ? e.getMessage() : e.getClass().getSimpleName())
                        .build());
                fail++;
            }
        }
        return WaterQualityBatchResponse.builder()
                .results(results)
                .successCount(ok)
                .failCount(fail)
                .build();
    }

    private WaterQualityResponse performCheckAndSave(WaterQualityRequest request) {
        String traceId = MDC.get(TraceIdFilter.MDC_KEY);
        String requestJsonRaw;
        try {
            requestJsonRaw = objectMapper.writeValueAsString(request);
        } catch (JsonProcessingException e) {
            requestJsonRaw = "{\"error\":\"serialize_request\"}";
        }
        final String requestJson = truncate(requestJsonRaw, 4000);

        final long t0 = System.currentTimeMillis();
        Long stationId = requireResolvedStationId(request.getStationCode());
        WaterQualityResponse response;
        try {
            response = aiPredictService.predictWithRetry(request);
        } catch (Exception e) {
            long failDurationMs = System.currentTimeMillis() - t0;
            businessMetrics.recordPredictDuration(failDurationMs, false);
            final Exception caught = e;
            try {
                requiresNewTx.executeWithoutResult(status ->
                        persistFailureLog(traceId, requestJson, t0, caught));
            } catch (Exception logEx) {
                log.error("persist failure log failed, traceId={}", traceId, logEx);
            }
            throw e;
        }
        long durationMs = System.currentTimeMillis() - t0;
        businessMetrics.recordPredictDuration(durationMs, true);

        WaterQualityRecord record = buildRecord(request, response, traceId, stationId);
        waterQualityRepository.save(record);
        businessMetrics.recordCheckCompleted(response.getPollutionLevel());

        persistSuccessLog(traceId, record.getId(), durationMs, requestJson, response);

        if (PollutionLevelThresholds.shouldAlert(
                response.getPollutionLevel(),
                waterAlertProperties.getThreshold()
        )) {
            AlertEvent alert = buildAlert(record, response);
            alertEventRepository.save(alert);
            businessMetrics.recordAlertCreated(alert.getSeverity(), alert.getPollutionLevel());
        }

        return response;
    }

    private WaterQualityRecord buildRecord(
            WaterQualityRequest request,
            WaterQualityResponse response,
            String traceId,
            Long stationId
    ) {
        LocalDateTime now = LocalDateTime.now();
        WaterQualityRecord record = new WaterQualityRecord();
        record.setWaterTemperatureC(request.getWaterTemperatureC());
        record.setPH(request.getPH());
        record.setDissolvedOxygenMgL(request.getDissolvedOxygenMgL());
        record.setConductivityUSCm(request.getConductivityUSCm());
        record.setTurbidityNTU(request.getTurbidityNTU());
        record.setNitrateMgL(request.getNitrateMgL());
        record.setAmmoniaNMgL(request.getAmmoniaNMgL());
        record.setTotalPhosphorusMgL(request.getTotalPhosphorusMgL());
        record.setCodMgL(request.getCodMgL());
        record.setBodMgL(request.getBodMgL());
        record.setHeavyMetalsPbUgL(request.getHeavyMetalsPbUgL());
        record.setPollutionLevel(response.getPollutionLevel());
        record.setCreateTime(now);
        record.setSampleTime(now);
        record.setStationId(stationId);
        record.setTraceId(traceId);
        record.setSource(RecordSource.API);
        return record;
    }

    private AlertEvent buildAlert(WaterQualityRecord record, WaterQualityResponse response) {
        String level = response.getPollutionLevel();
        int score = PollutionLevelThresholds.scoreOf(level);
        AlertEvent alert = new AlertEvent();
        alert.setWaterQualityRecordId(record.getId());
        alert.setStationId(record.getStationId());
        alert.setAlertType(ALERT_TYPE);
        alert.setSeverity(PollutionLevelThresholds.severityForScore(score));
        alert.setStatus("NEW");
        alert.setPollutionLevel(level);
        alert.setTitle("水质等级告警: " + level);
        alert.setDetail(
                "pollution_level=" + level
                        + ", score=" + score
                        + ", threshold=" + waterAlertProperties.getThreshold()
                        + ", parameter_cd=composite"
                        + ", model=" + RULE_CODE
        );
        alert.setRuleCode(RULE_CODE);
        alert.setCreatedAt(LocalDateTime.now());
        return alert;
    }

    private void persistSuccessLog(
            String traceId,
            Long recordId,
            long durationMs,
            String requestJson,
            WaterQualityResponse response
    ) {
        String responseJson;
        try {
            responseJson = truncate(objectMapper.writeValueAsString(response), 1000);
        } catch (JsonProcessingException e) {
            responseJson = "{}";
        }
        ModelCallLog log = new ModelCallLog();
        log.setWaterQualityRecordId(recordId);
        log.setTraceId(traceId);
        log.setSuccess(true);
        log.setHttpStatus(200);
        log.setDurationMs(durationMs);
        log.setRequestJson(requestJson);
        log.setResponseJson(responseJson);
        log.setCreatedAt(LocalDateTime.now());
        modelCallLogRepository.save(log);
    }

    private void persistFailureLog(String traceId, String requestJson, long t0, Exception e) {
        long durationMs = System.currentTimeMillis() - t0;
        Integer httpStatus = null;
        if (e instanceof FeignException fe) {
            int st = fe.status();
            if (st > 0) {
                httpStatus = st;
            }
        }
        ModelCallLog log = new ModelCallLog();
        log.setWaterQualityRecordId(null);
        log.setTraceId(traceId);
        log.setSuccess(false);
        log.setHttpStatus(httpStatus);
        log.setDurationMs(durationMs);
        log.setErrorMessage(truncate(e.getMessage(), 1000));
        log.setRequestJson(requestJson);
        log.setResponseJson(null);
        log.setCreatedAt(LocalDateTime.now());
        modelCallLogRepository.save(log);
    }

    private static String truncate(String s, int max) {
        if (s == null) {
            return null;
        }
        if (s.length() <= max) {
            return s;
        }
        return s.substring(0, max - 3) + "...";
    }

    /**
     * Check must bind to a registered station: fails without persist if code blank or unknown.
     */
    private Long requireResolvedStationId(String stationCode) {
        if (stationCode == null || stationCode.isBlank()) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "stationCode 必填，须为已登记站点编码"
            );
        }
        String normalized = stationCode.trim();
        return monitorStationRepository.findByStationCode(normalized)
                .map(MonitorStation::getId)
                .orElseThrow(() -> new ResponseStatusException(
                        HttpStatus.BAD_REQUEST,
                        "stationCode 不存在或未登记: " + normalized
                ));
    }
}
