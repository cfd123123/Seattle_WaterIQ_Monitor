package com.example.waterbusiness.service;

import com.example.waterbusiness.dto.StationResponse;
import com.example.waterbusiness.dto.StationUpsertRequest;
import com.example.waterbusiness.entity.MonitorStation;
import com.example.waterbusiness.repository.MonitorStationRepository;
import lombok.RequiredArgsConstructor;
import org.springframework.http.HttpStatus;
import org.springframework.stereotype.Service;
import org.springframework.transaction.annotation.Transactional;
import org.springframework.web.server.ResponseStatusException;

import java.time.LocalDateTime;
import java.util.List;

@Service
@RequiredArgsConstructor
public class MonitorStationService {

    private final MonitorStationRepository monitorStationRepository;
    private final UsgsSiteVerificationService usgsSiteVerificationService;

    /**
     * Create station; 409 if {@code stationCode} already exists (no overwrite).
     */
    @Transactional
    public StationResponse create(StationUpsertRequest request) {
        String code = normalizeStationCode(request.getStationCode());
        if (code.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "stationCode 不能为空");
        }
        if (monitorStationRepository.findByStationCode(code).isPresent()) {
            throw new ResponseStatusException(
                    HttpStatus.CONFLICT,
                    "站点已存在: " + code + "。请使用「保存修改」或 DELETE 后再添加。"
            );
        }
        LocalDateTime now = LocalDateTime.now();
        usgsSiteVerificationService.requireNwisSiteExistsIfConfigured(trimToNull(request.getExternalId()));
        MonitorStation station = new MonitorStation();
        applyFromRequest(station, request, code, now);
        return toResponse(monitorStationRepository.saveAndFlush(station));
    }

    /** Update by stationCode; 404 if missing. */
    @Transactional
    public StationResponse update(String stationCodePath, StationUpsertRequest request) {
        String code = normalizeStationCode(stationCodePath);
        if (code.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "stationCode 不能为空");
        }
        MonitorStation station = monitorStationRepository.findByStationCode(code)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "站点不存在: " + code));
        String bodyCode = normalizeStationCode(request.getStationCode());
        if (!bodyCode.isEmpty() && !bodyCode.equals(code)) {
            throw new ResponseStatusException(
                    HttpStatus.BAD_REQUEST,
                    "请求体中的 stationCode 与路径不一致（更新时不能改站点编码）。"
            );
        }
        LocalDateTime now = LocalDateTime.now();
        usgsSiteVerificationService.requireNwisSiteExistsIfConfigured(trimToNull(request.getExternalId()));
        applyFromRequest(station, request, code, now);
        return toResponse(monitorStationRepository.save(station));
    }

    @Transactional
    public void deleteByStationCode(String stationCodePath) {
        String code = normalizeStationCode(stationCodePath);
        if (code.isEmpty()) {
            throw new ResponseStatusException(HttpStatus.BAD_REQUEST, "stationCode 不能为空");
        }
        MonitorStation station = monitorStationRepository.findByStationCode(code)
                .orElseThrow(() -> new ResponseStatusException(HttpStatus.NOT_FOUND, "站点不存在: " + code));
        monitorStationRepository.delete(station);
    }

    private static String normalizeStationCode(String raw) {
        if (raw == null) {
            return "";
        }
        return raw.strip();
    }

    private void applyFromRequest(
            MonitorStation station,
            StationUpsertRequest request,
            String code,
            LocalDateTime now
    ) {
        if (station.getId() == null) {
            station.setStationCode(code);
            station.setCreatedAt(now);
        }
        station.setStationName(hasText(request.getStationName()) ? request.getStationName().trim() : code);
        station.setProvince(trimToNull(request.getProvince()));
        station.setCity(trimToNull(request.getCity()));
        station.setLatitude(request.getLatitude());
        station.setLongitude(request.getLongitude());
        station.setExternalId(trimToNull(request.getExternalId()));
        if (!hasText(station.getStatus())) {
            station.setStatus("ACTIVE");
        }
        station.setUpdatedAt(now);
    }

    public List<StationResponse> list() {
        return monitorStationRepository.findAll().stream()
                .map(this::toResponse)
                .toList();
    }

    private StationResponse toResponse(MonitorStation station) {
        return StationResponse.builder()
                .id(station.getId())
                .stationCode(station.getStationCode())
                .stationName(station.getStationName())
                .province(station.getProvince())
                .city(station.getCity())
                .latitude(station.getLatitude())
                .longitude(station.getLongitude())
                .externalId(station.getExternalId())
                .status(station.getStatus())
                .createdAt(station.getCreatedAt())
                .updatedAt(station.getUpdatedAt())
                .build();
    }

    private static boolean hasText(String value) {
        return value != null && !value.isBlank();
    }

    private static String trimToNull(String value) {
        if (!hasText(value)) {
            return null;
        }
        return value.trim();
    }
}
