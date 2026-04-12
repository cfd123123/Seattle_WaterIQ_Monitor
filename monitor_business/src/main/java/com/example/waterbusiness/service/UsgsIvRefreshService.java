package com.example.waterbusiness.service;

import com.example.waterbusiness.client.WaterAiMaintenanceClient;
import com.example.waterbusiness.dto.UsgsIvLatestCheckItem;
import com.example.waterbusiness.dto.UsgsIvPythonRefreshBody;
import com.example.waterbusiness.dto.UsgsIvRefreshRequest;
import com.example.waterbusiness.dto.UsgsIvRefreshResponse;
import com.example.waterbusiness.dto.UsgsIvRefreshResultDto;
import com.example.waterbusiness.dto.WaterQualityBatchResponse;
import com.example.waterbusiness.dto.WaterQualityRequest;
import com.example.waterbusiness.entity.MonitorStation;
import com.example.waterbusiness.repository.MonitorStationRepository;
import com.fasterxml.jackson.databind.ObjectMapper;
import io.github.resilience4j.retry.annotation.Retry;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.ArrayList;
import java.util.List;
import java.util.Objects;
import java.util.Optional;

@Service
@RequiredArgsConstructor
public class UsgsIvRefreshService {

    private static final Logger log = LoggerFactory.getLogger(UsgsIvRefreshService.class);

    /** Same per-request cap as {@link com.example.waterbusiness.dto.WaterQualityBatchRequest}; split into chunks. */
    private static final int IV_CHECK_BATCH_SIZE = 100;

    private final WaterAiMaintenanceClient waterAiMaintenanceClient;
    private final WaterQualityService waterQualityService;
    private final MonitorStationRepository monitorStationRepository;
    private final ObjectMapper objectMapper;
    private final TurbidityThresholdAlertService turbidityThresholdAlertService;

    @Retry(name = "waterAiUsgsIvRefreshRetry")
    public UsgsIvRefreshResultDto refreshWithRetry(UsgsIvRefreshRequest request) {
        UsgsIvRefreshRequest in = request != null ? request : new UsgsIvRefreshRequest();
        if (in.getDays() == null) {
            in.setDays(30);
        }
        boolean sync = Boolean.TRUE.equals(in.getRunChecksAfterRefresh());
        List<String> extraSites = listDistinctRegisteredExternalSiteNos();
        UsgsIvPythonRefreshBody pyBody = UsgsIvPythonRefreshBody.builder()
                .days(in.getDays())
                .includeLatestCheckPayloads(sync)
                .extraSiteNos(extraSites.isEmpty() ? null : extraSites)
                .build();
        UsgsIvRefreshResponse raw = waterAiMaintenanceClient.refreshUsgsIv(pyBody);
        UsgsIvRefreshResultDto out = toResultDto(raw);
        if (sync) {
            List<UsgsIvLatestCheckItem> items = raw.getIncrementalCheckPayloads();
            if (items != null && !items.isEmpty()) {
                List<WaterQualityRequest> checks = mapToCheckRequests(items);
                if (!checks.isEmpty()) {
                    int ok = 0;
                    int fail = 0;
                    for (int i = 0; i < checks.size(); i += IV_CHECK_BATCH_SIZE) {
                        int end = Math.min(i + IV_CHECK_BATCH_SIZE, checks.size());
                        WaterQualityBatchResponse batch = waterQualityService.checkBatch(checks.subList(i, end));
                        ok += batch.getSuccessCount();
                        fail += batch.getFailCount();
                    }
                    out.setCheckSyncSuccessCount(ok);
                    out.setCheckSyncFailCount(fail);
                } else {
                    out.setCheckSyncSuccessCount(0);
                    out.setCheckSyncFailCount(0);
                }
            } else {
                out.setCheckSyncSuccessCount(0);
                out.setCheckSyncFailCount(0);
            }
            try {
                turbidityThresholdAlertService.scanAndAlert();
            } catch (Exception e) {
                log.warn("turbidity threshold scan after IV refresh failed: {}", e.getMessage());
            }
        }
        return out;
    }

    private List<String> listDistinctRegisteredExternalSiteNos() {
        return monitorStationRepository.findAll().stream()
                .map(MonitorStation::getExternalId)
                .filter(Objects::nonNull)
                .map(String::trim)
                .filter(s -> !s.isEmpty())
                .distinct()
                .toList();
    }

    private static UsgsIvRefreshResultDto toResultDto(UsgsIvRefreshResponse raw) {
        UsgsIvRefreshResultDto d = new UsgsIvRefreshResultDto();
        d.setRegion(raw.getRegion());
        d.setSites(raw.getSites());
        d.setParameters(raw.getParameters());
        d.setStart(raw.getStart());
        d.setEnd(raw.getEnd());
        d.setRows(raw.getRows());
        d.setOut(raw.getOut());
        d.setMode(raw.getMode());
        d.setIncrementalRowsNew(raw.getIncrementalRowsNew());
        return d;
    }

    private List<WaterQualityRequest> mapToCheckRequests(List<UsgsIvLatestCheckItem> items) {
        List<WaterQualityRequest> list = new ArrayList<>(items.size());
        for (UsgsIvLatestCheckItem item : items) {
            if (item.getPayload() == null || item.getPayload().isEmpty()) {
                continue;
            }
            try {
                WaterQualityRequest req = objectMapper.convertValue(item.getPayload(), WaterQualityRequest.class);
                String ext = item.getSiteNo();
                if (ext == null || ext.isBlank()) {
                    log.info("skip IV check payload: missing site_no");
                    continue;
                }
                Optional<MonitorStation> reg = monitorStationRepository.findByExternalId(ext.trim());
                if (reg.isEmpty()) {
                    log.info(
                            "skip IV check: USGS site_no={} has no monitor_station.external_id match (register first)",
                            ext.trim()
                    );
                    continue;
                }
                req.setStationCode(reg.get().getStationCode());
                req.setObservedFields(item.getObservedFields());
                list.add(req);
            } catch (IllegalArgumentException e) {
                log.warn("skip IV check payload for site_no={}: {}", item.getSiteNo(), e.getMessage());
            }
        }
        return list;
    }
}
