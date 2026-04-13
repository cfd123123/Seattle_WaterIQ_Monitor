package com.example.waterbusiness.service;

import com.example.waterbusiness.client.WaterAiMaintenanceClient;
import com.example.waterbusiness.dto.UsgsIvPythonRefreshBody;
import com.example.waterbusiness.dto.UsgsIvRefreshRequest;
import com.example.waterbusiness.dto.UsgsIvRefreshResponse;
import com.example.waterbusiness.dto.UsgsIvRefreshResultDto;
import com.example.waterbusiness.entity.MonitorStation;
import com.example.waterbusiness.repository.MonitorStationRepository;
import io.github.resilience4j.retry.annotation.Retry;
import lombok.RequiredArgsConstructor;
import org.slf4j.Logger;
import org.slf4j.LoggerFactory;
import org.springframework.stereotype.Service;

import java.util.List;
import java.util.Objects;

@Service
@RequiredArgsConstructor
public class UsgsIvRefreshService {

    private static final Logger log = LoggerFactory.getLogger(UsgsIvRefreshService.class);

    private final WaterAiMaintenanceClient waterAiMaintenanceClient;
    private final MonitorStationRepository monitorStationRepository;
    private final TurbidityThresholdAlertService turbidityThresholdAlertService;

    @Retry(name = "waterAiUsgsIvRefreshRetry")
    public UsgsIvRefreshResultDto refreshWithRetry(UsgsIvRefreshRequest request) {
        UsgsIvRefreshRequest in = request != null ? request : new UsgsIvRefreshRequest();
        if (in.getDays() == null) {
            in.setDays(30);
        }
        boolean runPostRefresh = Boolean.TRUE.equals(in.getRunChecksAfterRefresh());
        List<String> extraSites = listDistinctRegisteredExternalSiteNos();
        UsgsIvPythonRefreshBody pyBody = UsgsIvPythonRefreshBody.builder()
                .days(in.getDays())
                .extraSiteNos(extraSites.isEmpty() ? null : extraSites)
                .build();
        UsgsIvRefreshResponse raw = waterAiMaintenanceClient.refreshUsgsIv(pyBody);
        UsgsIvRefreshResultDto out = toResultDto(raw);
        if (runPostRefresh) {
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
}
